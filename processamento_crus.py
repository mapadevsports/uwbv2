# processamento_crus.py (corrigido para calcular x,y por trilateração)
from fastapi import APIRouter, Body, HTTPException
from typing import List, Dict, Any
from datetime import datetime
from db import SessionLocal
import models

router = APIRouter(prefix="/processamento-crus", tags=["Processamento de dados crus"])

def _to_float_or_none(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None

@router.post("/ingest")
def ingest_processados(payload: Dict[str, Any] = Body(..., example={
    "dados": [
        {
            "id": 123,
            "tag_number": "4",
            "da": [100,110,103,0,0,0,0,0],
            "kx": 152.75,
            "ky": 101.3,
            "criado_em": "2025-10-11T20:49:21.90Z"
        }
    ]
})):
    """
    Recebe itens de `distancias_uwb` e grava em `distancias_processadas`
    calculando (x,y) por trilateração fechada usando A0=(0,0), A1=(kx,0), A2=(0,ky).
    """
    items: List[Dict[str, Any]] = payload.get("dados") or []
    if not items:
        raise HTTPException(status_code=400, detail="payload.dados vazio")

    db = SessionLocal()
    try:
        rows = []
        now = datetime.utcnow()

        for it in items:
            tag_number = str(it.get("tag_number", "")).strip()
            if not tag_number:
                continue

            da = it.get("da") or []
            if len(da) < 3:
                # precisa de d0,d1,d2
                continue

            d0 = _to_float_or_none(da[0])
            d1 = _to_float_or_none(da[1])
            d2 = _to_float_or_none(da[2])
            kx = _to_float_or_none(it.get("kx"))
            ky = _to_float_or_none(it.get("ky"))

            # validações mínimas
            if kx is None or ky is None or kx <= 0 or ky <= 0:
                continue
            if d0 is None or d1 is None or d2 is None:
                continue

            # trilateração fechada (sem LS)
            try:
                x_val = (d0*d0 - d1*d1 + kx*kx) / (2.0 * kx)
                y_val = (d0*d0 - d2*d2 + ky*ky) / (2.0 * ky)
            except ZeroDivisionError:
                continue

            # opcional: "clamp" dentro do retângulo definido pelas âncoras
            # x_val = max(0.0, min(x_val, kx))
            # y_val = max(0.0, min(y_val, ky))

            # campos opcionais (ainda não calculamos trilha/tempo)
            dist_perc = _to_float_or_none(it.get("distancia_percorrida"))
            tempo_seg = it.get("tempo_em_segundos")
            try:
                tempo_seg = int(tempo_seg) if tempo_seg is not None else None
            except (TypeError, ValueError):
                tempo_seg = None

            rows.append(
                models.DistanciaProcessada(
                    tag_number=tag_number,
                    x=float(x_val),
                    y=float(y_val),
                    distancia_percorrida=dist_perc,
                    tempo_em_segundos=tempo_seg,
                    criado_em=now,
                )
            )

        if not rows:
            return {"saved": 0}

        db.add_all(rows)
        db.commit()
        return {"saved": len(rows)}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao salvar em distancias_processadas: {e}")
    finally:
        db.close()
