# dados_crus.py
from fastapi import APIRouter, Body, HTTPException
from typing import List, Union
from datetime import datetime
import re

from db import SessionLocal
import models

router = APIRouter(prefix="/dados-crus", tags=["Dados crus"])

# Pega tid e o conteúdo de range:(...)
RE_LINE = re.compile(
    r"tid\s*:\s*(?P<tid>\d+).*?range\s*:\s*\((?P<rng>[^)]*)\)",
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
    m = RE_LINE.search(line)
    if not m:
        return None
    tid = m.group("tid").strip()
    parts = [p.strip() for p in m.group("rng").split(",")]
    vals = (parts + [""] * 8)[:8]  # garante 8 posições
    floats = [_to_float_or_none(v) for v in vals]
    return str(tid), floats

@router.post("/ingest")
def ingest_dados_crus(
    # aceita {"payload": "..."} ou {"payload": ["...", "..."]}
    payload: Union[str, List[str]] = Body(
        ...,
        embed=True,
        example=["AT+RANGE=tid:4,mask:01,seq:218,range:(3,0,0,0,0,0,0,0),rssi:(-79.31,0,0,0,0,0,0,0)"],
    )
):
    """
    Recebe string com 1+ linhas (separadas por \\n) **ou** lista de strings.
    Cada linha gera 1 insert em `distancias_uwb`.

    Obs.: `id` é autoincrement e não deve ser informado.
    """
    # Normaliza para lista de linhas
    if isinstance(payload, str):
        lines = [ln for ln in payload.splitlines() if ln.strip()]
    else:
        lines = [ln for ln in payload if isinstance(ln, str) and ln.strip()]

    if not lines:
        raise HTTPException(status_code=400, detail="payload vazio")

    saved, skipped = 0, 0
    db = SessionLocal()
    try:
        rows = []
        now = datetime.utcnow()  # timestamp único para o lote (pode trocar por um por linha, se preferir)
        for line in lines:
            parsed = parse_line(line)
            if not parsed:
                skipped += 1
                continue

            tag, vals = parsed
            rows.append(
                models.DistanciaUWB(
                    tag_number=tag,
                    da0=vals[0], da1=vals[1], da2=vals[2], da3=vals[3],
                    da4=vals[4], da5=vals[5], da6=vals[6], da7=vals[7],
                    criado_em=now,  # 👈 preenche para evitar NOT NULL
                )
            )

        if rows:
            db.add_all(rows)
            db.commit()
            saved = len(rows)

        return {"saved": saved, "skipped": skipped, "received_lines": len(lines)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
