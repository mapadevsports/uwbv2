# processamento_crus.py
from fastapi import APIRouter, Body, HTTPException
from typing import List, Dict
from db import SessionLocal
import models
import math
import numpy as np

router = APIRouter(prefix="/processamento-crus", tags=["Processamento de dados crus"])

@router.post("/ingest")
def processar_dados(dados: Dict = Body(...)):
    """
    Recebe dados crus de distâncias e calcula posição (x, y) por trilateração.
    """
    if "dados" not in dados:
        raise HTTPException(status_code=400, detail="Campo 'dados' ausente no payload")

    entradas = dados["dados"]
    if not isinstance(entradas, list) or not entradas:
        raise HTTPException(status_code=400, detail="Lista 'dados' vazia ou inválida")

    db = SessionLocal()
    processados = []

    try:
        for entrada in entradas:
            tag = entrada.get("tag_number")
            da = entrada.get("da", [])
            kx = entrada.get("kx")
            ky = entrada.get("ky")

            if not tag or len(da) < 3:
                continue

            r0, r1, r2 = da[:3]  # só as 3 primeiras distâncias

            if not all(isinstance(v, (int, float)) and v > 0 for v in [r0, r1, r2, kx, ky]):
                continue

            # Coordenadas das âncoras
            A0 = np.array([0.0, 0.0])
            A1 = np.array([kx, 0.0])
            A2 = np.array([0.0, ky])

            # Vetores de cálculo
            # (Equação simplificada de trilateração via mínimos quadrados)
            P1 = A1 - A0
            P2 = A2 - A0

            ex = P1 / np.linalg.norm(P1)
            i = np.dot(ex, P2)
            ey = (P2 - i * ex) / np.linalg.norm(P2 - i * ex)
            d = np.linalg.norm(P1)
            j = np.dot(ey, P2)

            x = (r0**2 - r1**2 + d**2) / (2 * d)
            y = (r0**2 - r2**2 + i**2 + j**2 - 2 * i * x) / (2 * j)

            pos = A0 + x * ex + y * ey
            x_calc, y_calc = pos[0], pos[1]

            # Salva resultado
            registro = models.DistanciaProcessada(
                tag_number=tag,
                x=x_calc,
                y=y_calc,
            )
            db.add(registro)
            processados.append({"tag": tag, "x": x_calc, "y": y_calc})

        db.commit()
        return {"processed": len(processados), "result": processados}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
