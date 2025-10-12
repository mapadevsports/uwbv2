# dados_crus.py
from fastapi import APIRouter, Body, HTTPException
from typing import List, Union
from datetime import datetime
import re
import requests

from db import SessionLocal
import models

router = APIRouter(prefix="/dados-crus", tags=["Dados crus"])

# ======================= AJUSTE GLOBAL =======================
# Offset em centímetros a ser SUBTRAÍDO de todas as medidas recebidas
# (da0..da7, kx, ky). Ajuste conforme sua calibração medida em campo.
DIST_OFFSET_CM: float = 40.0
# =============================================================

# URL da nova rota de processamento
PROCESS_URL = "https://uwb-api.onrender.com/processamento-crus/ingest"

# TAGs reservadas para calibração: devem ser ignoradas
CALIBRATION_TAGS = {"62", "63"}

# Regex que captura tid, range(...), kx e ky
RE_LINE = re.compile(
    r"tid\s*:\s*(?P<tid>\d+).*?"
    r"range\s*:\s*\((?P<rng>[^)]*)\).*?"
    r"kx\s*:\s*(?P<kx>[-+]?\d*\.?\d+).*?"
    r"ky\s*:\s*(?P<ky>[-+]?\d*\.?\d+)",
    re.IGNORECASE,
)

def _to_float_or_none(x: str):
    x = x.strip()
    if x == "" or x.lower() == "nan":
        return None
    try:
        return float(x)
    except ValueError:
        return None

def _apply_offset(v: float | None) -> float | None:
    """Subtrai o offset global quando houver valor."""
    if v is None:
        return None
    return v - DIST_OFFSET_CM

def parse_line(line: str):
    """Extrai tid, range[8], kx e ky de uma linha AT+RANGE."""
    m = RE_LINE.search(line)
    if not m:
        return None
    tid = m.group("tid").strip()
    parts = [p.strip() for p in m.group("rng").split(",")]
    vals = (parts + [""] * 8)[:8]
    floats = [_to_float_or_none(v) for v in vals]
    kx = _to_float_or_none(m.group("kx"))
    ky = _to_float_or_none(m.group("ky"))
    return tid, floats, kx, ky


@router.post("/ingest")
def ingest_dados_crus(
    payload: Union[str, List[str]] = Body(
        ...,
        embed=True,
        example=[
            "AT+RANGE=tid:4,mask:01,seq:218,range:(100,110,103,0,0,0,0,0),kx:152.75,ky:101.3,user:user1"
        ],
    )
):
    """
    Recebe string ou lista de strings (linhas AT+RANGE),
    grava em `distancias_uwb` e, depois, chama /processamento-crus/ingest.

    Observação: leituras das TAGs 62 e 63 (calibração) são ignoradas:
    não são persistidas e não são encaminhadas.
    """
    # Normaliza payload → lista de linhas válidas
    if isinstance(payload, str):
        lines = [ln for ln in payload.splitlines() if ln.strip()]
    else:
        lines = [ln for ln in payload if isinstance(ln, str) and ln.strip()]

    if not lines:
        raise HTTPException(status_code=400, detail="payload vazio")

    db = SessionLocal()
    try:
        rows = []
        now = datetime.utcnow()
        skipped_calibration = 0
        skipped_invalid = 0

        for line in lines:
            parsed = parse_line(line)
            if not parsed:
                skipped_invalid += 1
                continue

            tag, vals, kx, ky = parsed

            # IGNORA calibração (tags 62 e 63)
            if tag in CALIBRATION_TAGS:
                skipped_calibration += 1
                continue

            # Aplica offset global (subtração) em todas as medidas
            adj_vals = [_apply_offset(v) for v in vals]
            adj_kx = _apply_offset(kx)
            adj_ky = _apply_offset(ky)

            rows.append(
                models.DistanciaUWB(
                    tag_number=tag,
                    da0=adj_vals[0], da1=adj_vals[1], da2=adj_vals[2], da3=adj_vals[3],
                    da4=adj_vals[4], da5=adj_vals[5], da6=adj_vals[6], da7=adj_vals[7],
                    kx=adj_kx, ky=adj_ky, criado_em=now,
                )
            )

        if not rows:
            # nada elegível para gravação após filtros
            raise HTTPException(
                status_code=422,
                detail="nenhuma linha elegível (todas inválidas ou de calibração 62/63)",
            )

        db.add_all(rows)
        db.commit()

        # Prepara payload simplificado para o processamento (apenas o que foi salvo)
        serialized = [
            {
                "id": r.id,
                "tag_number": r.tag_number,
                "da": [r.da0, r.da1, r.da2, r.da3, r.da4, r.da5, r.da6, r.da7],
                "kx": r.kx,
                "ky": r.ky,
                "criado_em": r.criado_em.isoformat() if r.criado_em else None,
            }
            for r in rows
        ]

        # Envia os dados recém-gravados para a rota de processamento
        sent_to_processamento = False
        try:
            res = requests.post(PROCESS_URL, json={"dados": serialized}, timeout=3)
            sent_to_processamento = res.status_code in (200, 201)
            if not sent_to_processamento:
                print(f"[AVISO] Falha ao acionar processamento_crus: {res.status_code} {res.text}")
        except Exception as e:
            print(f"[ERRO] Não foi possível contatar {PROCESS_URL}: {e}")

        return {
            "saved": len(rows),
            "skipped_calibration": skipped_calibration,
            "skipped_invalid": skipped_invalid,
            "sent_to_processamento": sent_to_processamento,
            "dist_offset_cm": DIST_OFFSET_CM,
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao salvar: {e}")
    finally:
        db.close()
