# dados_crus.py
from fastapi import APIRouter, Body
from typing import List, Union
import re

from db import SessionLocal
import models

router = APIRouter(prefix="/dados-crus", tags=["Dados crus"])

# Regex robusta: pega tid e tudo que estiver dentro de range:(...)
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
    """
    Retorna (tag_number:str, valores:list[float|None] com 8 posições) ou None se não casar.
    """
    m = RE_LINE.search(line)
    if not m:
        return None

    tid = m.group("tid").strip()
    parts = [p.strip() for p in m.group("rng").split(",")]
    # garante 8 posições (preenche com None se vier menos)
    vals = (parts + [""] * 8)[:8]
    floats = [_to_float_or_none(v) for v in vals]
    return str(tid), floats  # tag_number é string (tabela aceita varchar)

@router.post("/ingest")
def ingest_dados_crus(payload: Union[str, List[str]] = Body(..., example=[
    "AT+RANGE=tid:4,mask:01,seq:218,range:(3,0,0,0,0,0,0,0),rssi:(-79.31,0,0,0,0,0,0,0)"
])):
    """
    Recebe **string** com 1+ linhas (separadas por \\n) **ou** lista de strings.
    Para cada linha no formato:
      AT+RANGE=tid:<N>,...,range:(v0,v1,v2,v3,v4,v5,v6,v7),...
    grava em distancias_uwb:
      - tag_number = <N>
      - da0..da7 = v0..v7
    """
    # Normaliza para lista de linhas
    if isinstance(payload, str):
        lines = [ln for ln in payload.splitlines() if ln.strip()]
    else:
        lines = [ln for ln in payload if isinstance(ln, str) and ln.strip()]

    saved, skipped = 0, 0
    db = SessionLocal()
    try:
        rows = []
        for line in lines:
            parsed = parse_line(line)
            if not parsed:
                skipped += 1
                continue
            tag, vals = parsed
            row = models.DistanciaUWB(
                tag_number=tag,
                da0=vals[0], da1=vals[1], da2=vals[2], da3=vals[3],
                da4=vals[4], da5=vals[5], da6=vals[6], da7=vals[7],
            )
            rows.append(row)

        if rows:
            db.add_all(rows)
            db.commit()
            saved = len(rows)

        return {"saved": saved, "skipped": skipped, "received_lines": len(lines)}
    finally:
        db.close()
