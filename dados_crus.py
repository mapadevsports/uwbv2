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
DIST_OFFSET_CM: float = 40.0
# =============================================================

# URL da nova rota de processamento
PROCESS_URL = "https://uwb-api.onrender.com/processamento-crus/ingest"

# TAGs reservadas para calibração (ignorar)
CALIBRATION_TAGS = {"62", "63"}

# Regex que captura tid, range(...), kx, ky, cmd e user
RE_LINE = re.compile(
    r"tid\s*:\s*(?P<tid>\d+).*?"
    r"range\s*:\s*\((?P<rng>[^)]*)\).*?"
    r"kx\s*:\s*(?P<kx>[-+]?\d*\.?\d+).*?"
    r"ky\s*:\s*(?P<ky>[-+]?\d*\.?\d+)"
    r"(?:.*?cmd\s*:\s*(?P<cmd>\d+))?"
    r"(?:.*?user\s*:\s*(?P<user>[\w.@+\-]+))?",
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
    """Aplica offset global nas medidas."""
    if v is None:
        return None
    return v - DIST_OFFSET_CM


def _fmt(v: float | None) -> str | None:
    """Converte para string (colunas kx/ky são varchar)."""
    if v is None:
        return None
    return str(v)


def parse_line(line: str):
    """Extrai tid, range[8], kx, ky, cmd, user de uma linha AT+RANGE."""
    m = RE_LINE.search(line)
    if not m:
        return None
    tid = m.group("tid").strip()
    parts = [p.strip() for p in m.group("rng").split(",")]
    vals = (parts + [""] * 8)[:8]
    floats = [_to_float_or_none(v) for v in vals]
    kx = _to_float_or_none(m.group("kx"))
    ky = _to_float_or_none(m.group("ky"))
    cmd = int(m.group("cmd")) if m.group("cmd") else 0
    user = (m.group("user") or "").strip() or None
    return tid, floats, kx, ky, cmd, user


# ---------- helpers de relatório ----------
def _open_or_update_relatorio(db, user: str, kx_f: float | None, ky_f: float | None):
    """
    Abre/atualiza um relatório ativo (fim_do_relatorio IS NULL) para o usuário.
    - Se não existir, cria com inicio_do_relatorio = agora.
    - Atualiza kx/ky (varchar) quando fornecidos.
    """
    now = datetime.utcnow()
    rel = (
        db.query(models.Relatorio)
        .filter(models.Relatorio.user == user, models.Relatorio.fim_do_relatorio.is_(None))
        .order_by(models.Relatorio.relatorio_number.desc())
        .first()
    )

    kx_s = _fmt(kx_f)
    ky_s = _fmt(ky_f)

    if rel is None:
        rel = models.Relatorio(
            user=user,
            inicio_do_relatorio=now,
            kx=kx_s,
            ky=ky_s,
            # nome=user opcional
        )
        db.add(rel)
    else:
        if getattr(rel, "inicio_do_relatorio", None) is None:
            rel.inicio_do_relatorio = now
        if kx_s is not None:
            rel.kx = kx_s
        if ky_s is not None:
            rel.ky = ky_s
    # commit será feito depois


def _close_relatorio(db, user: str):
    """Fecha o relatório ativo do usuário (fim_do_relatorio = agora)."""
    rel = (
        db.query(models.Relatorio)
        .filter(models.Relatorio.user == user, models.Relatorio.fim_do_relatorio.is_(None))
        .order_by(models.Relatorio.relatorio_number.desc())
        .first()
    )
    if rel:
        rel.fim_do_relatorio = datetime.utcnow()


@router.post("/ingest")
def ingest_dados_crus(
    payload: Union[str, List[str]] = Body(
        ...,
        embed=True,
        example=[
            "AT+RANGE=tid:4,mask:01,seq:218,range:(100,110,103,0,0,0,0,0),kx:152.75,ky:101.3,cmd:2,user:user1"
        ],
    )
):
    """
    Fluxo:
      - cmd=0: descarta linha (não grava nem encaminha)
      - cmd=1: abre/atualiza relatório (inicio_do_relatorio, kx, ky)
      - cmd=3: fecha relatório (fim_do_relatorio)
      - Tags 62/63: ignoradas
      - Demais casos: grava normalmente
    """
    if isinstance(payload, str):
        lines = [ln for ln in payload.splitlines() if ln.strip()]
    else:
        lines = [ln for ln in payload if isinstance(ln, str) and ln.strip()]

    if not lines:
        raise HTTPException(status_code=400, detail="payload vazio")

    db = SessionLocal()
    try:
        rows_to_save = []
        now = datetime.utcnow()
        skipped_calibration = 0
        skipped_invalid = 0
        skipped_cmd0 = 0
        relatorios_abertos = 0
        relatorios_fechados = 0

        for line in lines:
            parsed = parse_line(line)
            if not parsed:
                skipped_invalid += 1
                continue

            tag, vals, kx, ky, cmd, user = parsed

            # Comandos
            if cmd == 1 and user:
                _open_or_update_relatorio(db, user, _apply_offset(kx), _apply_offset(ky))
                relatorios_abertos += 1
            elif cmd == 3 and user:
                _close_relatorio(db, user)
                relatorios_fechados += 1

            # Descartar cmd=0
            if cmd == 0:
                skipped_cmd0 += 1
                continue

            # Ignorar calibração
            if tag in CALIBRATION_TAGS:
                skipped_calibration += 1
                continue

            # Grava distâncias
            adj_vals = [_apply_offset(v) for v in vals]
            adj_kx = _apply_offset(kx)
            adj_ky = _apply_offset(ky)

            rows_to_save.append(
                models.DistanciaUWB(
                    tag_number=tag,
                    da0=adj_vals[0], da1=adj_vals[1], da2=adj_vals[2], da3=adj_vals[3],
                    da4=adj_vals[4], da5=adj_vals[5], da6=adj_vals[6], da7=adj_vals[7],
                    kx=adj_kx, ky=adj_ky, criado_em=now,
                )
            )

        # Commit único
        if rows_to_save:
            db.add_all(rows_to_save)
        db.commit()

        serialized = [
            {
                "id": r.id,
                "tag_number": r.tag_number,
                "da": [r.da0, r.da1, r.da2, r.da3, r.da4, r.da5, r.da6, r.da7],
                "kx": r.kx,
                "ky": r.ky,
                "criado_em": r.criado_em.isoformat() if r.criado_em else None,
            }
            for r in rows_to_save
        ]

        sent_to_processamento = False
        if serialized:
            try:
                res = requests.post(PROCESS_URL, json={"dados": serialized}, timeout=3)
                sent_to_processamento = res.status_code in (200, 201)
                if not sent_to_processamento:
                    print(f"[AVISO] Falha ao acionar processamento_crus: {res.status_code} {res.text}")
            except Exception as e:
                print(f"[ERRO] Falha ao contatar {PROCESS_URL}: {e}")

        return {
            "saved": len(serialized),
            "skipped_cmd0": skipped_cmd0,
            "skipped_calibration": skipped_calibration,
            "skipped_invalid": skipped_invalid,
            "relatorios_abertos_ou_atualizados": relatorios_abertos,
            "relatorios_fechados": relatorios_fechados,
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
