# dados_crus.py
from fastapi import APIRouter, Body, HTTPException, Query
from typing import List, Union, Tuple, Optional, Dict, Any
from datetime import datetime
import re

from db import SessionLocal
import models

router = APIRouter(prefix="/dados-crus", tags=["Dados crus"])

# tid e o conteúdo de range:(...)
RE_LINE = re.compile(
    r"tid\s*:\s*(?P<tid>\d+).*?range\s*:\s*\((?P<rng>[^)]*)\)",
    re.IGNORECASE,
)

# números: aceita -, +, inteiros, .123, 123., 123.45
NUM = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"

# kx/ky: muito tolerante, aceita "...,kx:0.00,ky:358.95,user:..." etc.
RE_KX = re.compile(rf"kx\s*:\s*({NUM})(?=,|$|\s)", re.IGNORECASE)
RE_KY = re.compile(rf"ky\s*:\s*({NUM})(?=,|$|\s)", re.IGNORECASE)


def _to_float_or_none(x: str):
    x = x.strip()
    if x == "" or x.lower() == "nan":
        return None
    try:
        return float(x)
    except ValueError:
        return None


def parse_line(line: str) -> Optional[Tuple[str, List[Optional[float]], Optional[float], Optional[float]]]:
    """
    Retorna:
      (tag_number, [da0..da7], kx|None, ky|None)
    ou None se a linha não casar com o padrão mínimo (tid + range).
    """
    m = RE_LINE.search(line)
    if not m:
        return None

    tid = m.group("tid").strip()

    # range -> da0..da7
    parts = [p.strip() for p in m.group("rng").split(",")]
    vals = (parts + [""] * 8)[:8]
    floats = [_to_float_or_none(v) for v in vals]

    # kx/ky em qualquer lugar da linha
    kx_m = RE_KX.search(line)
    ky_m = RE_KY.search(line)
    kx = float(kx_m.group(1)) if kx_m else None
    ky = float(ky_m.group(1)) if ky_m else None

    return str(tid), floats, kx, ky


@router.get("/debug-parse")
def debug_parse(line: str = Query(..., description="Linha AT+RANGE crua")) -> Dict[str, Any]:
    """
    Só parseia a linha e retorna o que seria gravado.
    Útil para verificar rapidamente kx/ky e da0..da7.
    """
    parsed = parse_line(line)
    if not parsed:
        raise HTTPException(status_code=422, detail="Linha não casou com o padrão (precisa de tid e range:(...))")

    tag, vals, kx, ky = parsed
    return {
        "tag_number": tag,
        "da": vals,
        "kx": kx,
        "ky": ky,
    }


@router.post("/ingest")
def ingest_dados_crus(
    # aceita {"payload": "..."} ou {"payload": ["...", "..."]}
    payload: Union[str, List[str]] = Body(
        ...,
        embed=True,
        example=[
            "AT+RANGE=tid:63,range:(366,329,0,0,0,0,0,0),kx:0.00,ky:358.95,user:user1"
        ],
    )
):
    """
    Recebe string com 1+ linhas (separadas por \\n) **ou** lista de strings.
    Cada linha gera 1 insert em `distancias_uwb`.

    Campos:
      - obrigatórios: tid, range:(da0..da7)
      - opcionais: kx:<float>, ky:<float> (em qualquer posição)
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
    parsed_preview: List[Dict[str, Any]] = []  # devolvemos uma amostra do parse

    db = SessionLocal()
    try:
        rows = []
        now = datetime.utcnow()
        for line in lines:
            parsed = parse_line(line)
            if not parsed:
                skipped += 1
                continue

            tag, vals, kx, ky = parsed
            parsed_preview.append({"tag": tag, "da": vals, "kx": kx, "ky": ky})

            rows.append(
                models.DistanciaUWB(
                    tag_number=tag,
                    da0=vals[0], da1=vals[1], da2=vals[2], da3=vals[3],
                    da4=vals[4], da5=vals[5], da6=vals[6], da7=vals[7],
                    kx=kx, ky=ky,
                    criado_em=now,
                )
            )

        if rows:
            db.add_all(rows)
            db.commit()
            saved = len(rows)

        # devolvemos só uma amostra das primeiras 5 linhas parseadas
        return {
            "saved": saved,
            "skipped": skipped,
            "received_lines": len(lines),
            "preview": parsed_preview[:5],
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
