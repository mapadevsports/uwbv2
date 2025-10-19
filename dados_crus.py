# dados_crus.py (com diagnóstico detalhado)
from fastapi import APIRouter, Body, HTTPException, Query
from typing import List, Union, Optional
from datetime import datetime
import re
import requests
import logging
import traceback

from sqlalchemy import text

from db import SessionLocal
import models

router = APIRouter(prefix="/dados-crus", tags=["Dados crus"])

log = logging.getLogger("uvicorn.error")

# ======================= AJUSTE GLOBAL =======================
DIST_OFFSET_CM: float = 40.0
# =============================================================

PROCESS_URL = "https://uwb-api.onrender.com/processamento-crus/ingest"
CALIBRATION_TAGS = {"62", "63"}

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
    if v is None:
        return None
    return v - DIST_OFFSET_CM

def _fmt_str(v: float | None) -> Optional[str]:
    if v is None:
        return None
    return str(v)

def parse_line(line: str):
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

# ---------- RELATORIO (SQL cru com nomes exatos) ----------
def _relatorio_open_or_update(db, user: str, kx_f: float | None, ky_f: float | None):
    if not user:
        return
    now = datetime.utcnow()
    kx_s = _fmt_str(_apply_offset(kx_f))
    ky_s = _fmt_str(_apply_offset(ky_f))

    row = db.execute(
        text(
            'SELECT relatorio_number FROM relatorio '
            'WHERE "user" = :user AND fim_do_relatorio IS NULL '
            'ORDER BY relatorio_number DESC LIMIT 1'
        ),
        {"user": user},
    ).mappings().first()

    if row is None:
        db.execute(
            text(
                'INSERT INTO relatorio ("user", inicio_do_relatorio, kx, ky) '
                'VALUES (:user, :inicio, :kx, :ky)'
            ),
            {"user": user, "inicio": now, "kx": kx_s, "ky": ky_s},
        )
    else:
        db.execute(
            text(
                'UPDATE relatorio '
                'SET inicio_do_relatorio = COALESCE(inicio_do_relatorio, :inicio), '
                '    kx = COALESCE(:kx, kx), '
                '    ky = COALESCE(:ky, ky) '
                'WHERE relatorio_number = :id'
            ),
            {"inicio": now, "kx": kx_s, "ky": ky_s, "id": row["relatorio_number"]},
        )

def _relatorio_close(db, user: str):
    if not user:
        return
    now = datetime.utcnow()
    row = db.execute(
        text(
            'SELECT relatorio_number FROM relatorio '
            'WHERE "user" = :user AND fim_do_relatorio IS NULL '
            'ORDER BY relatorio_number DESC LIMIT 1'
        ),
        {"user": user},
    ).mappings().first()
    if row:
        db.execute(
            text(
                'UPDATE relatorio SET fim_do_relatorio = :fim '
                'WHERE relatorio_number = :id'
            ),
            {"fim": now, "id": row["relatorio_number"]},
        )

# ---------- util de diagnóstico ----------
def _schema_columns(db, table: str):
    q = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name=:t
        ORDER BY ordinal_position
    """)
    return [r[0] for r in db.execute(q, {"t": table}).fetchall()]

@router.post("/ingest")
def ingest_dados_crus(
    payload: Union[str, List[str]] = Body(
        ...,
        embed=True,
        example=[
            "AT+RANGE=tid:4,mask:01,seq:218,range:(100,110,103,0,0,0,0,0),kx:152.75,ky:101.3,cmd:2,user:user1"
        ],
    ),
    debug: int = Query(0, description="Defina 1 para retornar info de diagnóstico"),
):
    """
    Regras:
      - cmd=0: descarta (não grava, não encaminha)
      - cmd=1: abre/atualiza relatório (inicio_do_relatorio, kx, ky)
      - cmd=3: fecha relatório (fim_do_relatorio)
      - TAG 62/63: ignora (não grava/encaminha)
      - demais casos: grava em distancias_uwb e encaminha
    """
    # Normalização
    if isinstance(payload, str):
        lines = [ln for ln in payload.splitlines() if ln.strip()]
    else:
        lines = [ln for ln in payload if isinstance(ln, str) and ln.strip()]

    if not lines:
        raise HTTPException(status_code=400, detail="payload vazio")

    db = SessionLocal()
    try:
        rows_to_save = []
        skipped_calibration = 0
        skipped_invalid = 0
        skipped_cmd0 = 0
        relatorios_abertos = 0
        relatorios_fechados = 0
        parsed_samples = []

        # ---------- PARSE ----------
        try:
            for line in lines:
                parsed = parse_line(line)
                if not parsed:
                    skipped_invalid += 1
                    continue
                tag, vals, kx, ky, cmd, user = parsed
                parsed_samples.append(
                    {"tag": tag, "cmd": cmd, "user": user, "kx": kx, "ky": ky, "vals": vals[:3]}
                )

                # comandos de relatório
                if cmd == 1 and user:
                    try:
                        _relatorio_open_or_update(db, user, kx, ky)
                        relatorios_abertos += 1
                    except Exception as e:
                        log.exception(f"[RELATORIO cmd=1] user={user} erro: {e}")
                        raise

                elif cmd == 3 and user:
                    try:
                        _relatorio_close(db, user)
                        relatorios_fechados += 1
                    except Exception as e:
                        log.exception(f"[RELATORIO cmd=3] user={user} erro: {e}")
                        raise

                # descartes
                if cmd == 0:
                    skipped_cmd0 += 1
                    continue

                if tag in CALIBRATION_TAGS:
                    skipped_calibration += 1
                    continue

                # preparar insert em distancias_uwb
                adj_vals = [_apply_offset(v) for v in vals]
                adj_kx = _apply_offset(kx)
                adj_ky = _apply_offset(ky)

                rows_to_save.append(
                    models.DistanciaUWB(
                        tag_number=tag,
                        da0=adj_vals[0], da1=adj_vals[1], da2=adj_vals[2], da3=adj_vals[3],
                        da4=adj_vals[4], da5=adj_vals[5], da6=adj_vals[6], da7=adj_vals[7],
                        kx=adj_kx, ky=adj_ky,
                        # criado_em: deixa o server_default cuidar
                    )
                )
        except Exception as e:
            log.exception(f"[PARSE/PIPELINE] erro: {e}\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=f"Falha no parsing/pipeline: {e}")

        # ---------- INSERT distancias_uwb / COMMIT ----------
        try:
            if rows_to_save:
                db.add_all(rows_to_save)
            db.commit()
        except Exception as e:
            db.rollback()
            # Diagnóstico de schema em caso de falha no insert
            try:
                cols_dist = _schema_columns(db, "distancias_uwb")
            except Exception:
                cols_dist = ["<falha ao inspecionar schema>"]
            log.exception(f"[DB-COMMIT] erro ao gravar distancias_uwb: {e}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail={
                    "erro": "Falha ao gravar distancias_uwb",
                    "exc": str(e),
                    "tabela": "distancias_uwb",
                    "colunas_detectadas": cols_dist,
                },
            )

        # ---------- CHAMADA processamento-crus ----------
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
                    log.warning(f"[PROC] Falha ao acionar processamento_crus: {res.status_code} {res.text}")
            except Exception as e:
                log.exception(f"[PROC] erro ao contatar processamento: {e}")

        # ---------- RESPOSTA ----------
        resp = {
            "saved": len(serialized),
            "skipped_cmd0": skipped_cmd0,
            "skipped_calibration": skipped_calibration,
            "skipped_invalid": skipped_invalid,
            "relatorios_abertos_ou_atualizados": relatorios_abertos,
            "relatorios_fechados": relatorios_fechados,
            "sent_to_processamento": sent_to_processamento,
            "dist_offset_cm": DIST_OFFSET_CM,
        }

        if debug:
            # anexa informações úteis para depuração
            try:
                resp["__schema_relatorio__"] = _schema_columns(db, "relatorio")
                resp["__schema_distancias__"] = _schema_columns(db, "distancias_uwb")
            except Exception:
                resp["__schema_relatorio__"] = ["<falha ao inspecionar>"]
                resp["__schema_distancias__"] = ["<falha ao inspecionar>"]
            resp["__parsed_sample__"] = parsed_samples[:5]

        return resp

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        log.exception(f"[INGEST] erro inesperado: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Erro inesperado: {e}")
    finally:
        db.close()
