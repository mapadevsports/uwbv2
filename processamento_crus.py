# processamento_crus.py
from fastapi import APIRouter, Body, HTTPException
from typing import List, Dict, Any
from datetime import datetime
from db import SessionLocal
import models

router = APIRouter(prefix="/processamento-crus", tags=["Processamento de dados crus"])

@router.post("/ingest")
def ingest_processados(payload: Dict[str, Any] = Body(..., example={
    "dados": [
        {
            "id": 123,
            "tag_number": "4",
            "da": [3,0,0,0,0,0,0,0],
            "kx": 79.3,
            "ky": 51.0,
            "criado_em": "2025-10-11T20:49:21.90Z"
        }
    ]
})):
    """
    Recebe uma lista 'dados' já persistidos em distancias_uwb e insere
    em distancias_processadas os campos calculados. Aqui apenas garantimos:
    - conversão de tipos para float/int nativos
    - preenchimento de criado_em (NOT NULL)
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
                # pula entradas sem tag_number
                continue

            # Se já vieram calculados, use-os; caso contrário, coloque 0.0
            x_val = it.get("x", it.get("kx", 0.0))
            y_val = it.get("y", it.get("ky", 0.0))

            # Converte para floats nativos do Python (evita np.float64)
            try:
                x_val = float(x_val) if x_val is not None else None
                y_val = float(y_val) if y_val is not None else None
            except (TypeError, ValueError):
                # Se não converter, pula a linha
                continue

            # Campos opcionais (podem ficar nulos)
            dist_perc = it.get("distancia_percorrida", None)
            try:
                dist_perc = float(dist_perc) if dist_perc is not None else None
            except (TypeError, ValueError):
                dist_perc = None

            tempo_seg = it.get("tempo_em_segundos", None)
            try:
                tempo_seg = int(tempo_seg) if tempo_seg is not None else None
            except (TypeError, ValueError):
                tempo_seg = None

            rows.append(
                models.DistanciaProcessada(
                    tag_number=tag_number,
                    x=x_val,
                    y=y_val,
                    distancia_percorrida=dist_perc,
                    tempo_em_segundos=tempo_seg,
                    criado_em=now,  # 👈 evita NOT NULL
                )
            )

        if not rows:
            # Nada válido para inserir
            return {"saved": 0}

        db.add_all(rows)
        db.commit()
        return {"saved": len(rows)}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Erro ao salvar em distancias_processadas: {e}")
    finally:
        db.close()
