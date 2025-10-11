# dados_crus.py
from fastapi import APIRouter, Body, HTTPException
from typing import List, Union
from datetime import datetime
import re
import requests

from db import SessionLocal
import models

router = APIRouter(prefix="/dados-crus", tags=["Dados crus"])

# URL da nova rota de processamento
PROCESS_URL = "https://uwb-api.onrender.com/processamento-crus/ingest"

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

def parse_line(line: str):
    """Extrai tid, range[], kx e ky de uma linha AT+RANGE."""
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
            "AT+RANGE=tid:4,mask:01,seq:218,range:(3,0,0,0,0,0,0,0),kx:100.0,ky:200.0,user:user1"
        ],
    )
):
    """
    Recebe string ou lista de strings (linhas AT+RANGE) e grava em `distancias_uwb`.
    Após salvar, envia os mesmos dados à rota /processamento-crus/ingest.
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

        for line in lines:
            parsed = parse_line(line)
            if not parsed:
                continue
            tag, vals, kx, ky = parsed
            rows.append(
                models.DistanciaUWB(
                    tag_number=tag,
                    da0=vals[0], da1=vals[1], da2=vals[2], da3=vals[3],
                    da4=vals[4], da5=vals[5], da6=vals[6], da7=vals[7],
                    kx=kx, ky=ky, criado_em=now,
                )
            )

        if not rows:
            raise HTTPException(status_code=422, detail="nenhuma linha válida encontrada")

        db.add_all(rows)
        db.commit()

        # Prepara payload simplificado para o processamento
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
        try:
            res = requests.post(PROCESS_URL, json={"dados": serialized}, timeout=3)
            if res.status_code not in (200, 201):
                print(f"[AVISO] Falha ao acionar processamento_crus: {res.status_code} {res.text}")
        except Exception as e:
            print(f"[ERRO] Não foi possível contatar {PROCESS_URL}: {e}")

        return {"saved": len(rows), "sent_to_processamento": True}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao salvar: {e}")
    finally:
        db.close()
