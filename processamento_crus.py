# processamento_crus.py (trilateração + distância/tempo com cache em memória)
from fastapi import APIRouter, Body, HTTPException
from typing import List, Dict, Any, Tuple
from datetime import datetime, timezone
import math

from db import SessionLocal
import models

router = APIRouter(prefix="/processamento-crus", tags=["Processamento de dados crus"])

# Cache em memória para última posição por tag:
# { "tag_number": (last_x, last_y, last_ts_utc) }
LAST_POS: Dict[str, Tuple[float, float, datetime]] = {}


def _to_float_or_none(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _parse_iso_ts(ts: Any) -> datetime:
    """
    Tenta parsear um ISO8601. Se vier 'Z' (UTC), converte para '+00:00'.
    Se não vier nada ou falhar, retorna datetime.utcnow() (ciente em UTC).
    """
    if isinstance(ts, datetime):
        # Garanta timezone-aware em UTC
        return ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    if not ts:
        return datetime.utcnow().replace(tzinfo=timezone.utc)

    s = str(ts).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc)


@router.post("/ingest")
def ingest_processados(payload: Dict[str, Any] = Body(..., example={
    "dados": [
        {
            "id": 123,
            "tag_number": "4",
            "da": [100, 110, 103, 0, 0, 0, 0, 0],
            "kx": 152.75,
            "ky": 101.3,
            "criado_em": "2025-10-11T20:49:21.900Z"
        }
    ]
})):
    """
    Recebe itens de `distancias_uwb` e grava em `distancias_processadas`:
      1) Calcula (x, y) por trilateração fechada usando A0=(0,0), A1=(kx,0), A2=(0,ky).
      2) Calcula distancia_percorrida como distância Euclidiana entre (x,y) atual e última posição da mesma tag.
      3) Calcula tempo_em_segundos como diferença de timestamps entre atual e último ponto da mesma tag.

    Observações:
      - Cache de última posição por tag é em memória (reseta em restart, o que aqui é desejado).
      - Se não houver ponto anterior, distancia_percorrida e tempo_em_segundos ficam None (ou 0 se preferir).
    """
    items: List[Dict[str, Any]] = payload.get("dados") or []
    if not items:
        raise HTTPException(status_code=400, detail="payload.dados vazio")

    db = SessionLocal()
    try:
        rows = []

        for it in items:
            tag_number = str(it.get("tag_number", "")).strip()
            if not tag_number:
                continue

            da = it.get("da") or []
            if len(da) < 3:
                # precisa de d0, d1, d2
                continue

            # distâncias para A0, A1, A2
            d0 = _to_float_or_none(da[0])
            d1 = _to_float_or_none(da[1])
            d2 = _to_float_or_none(da[2])

            # dimensões do retângulo (distâncias entre âncoras)
            kx = _to_float_or_none(it.get("kx"))
            ky = _to_float_or_none(it.get("ky"))

            # validações mínimas
            if kx is None or ky is None or kx <= 0 or ky <= 0:
                continue
            if d0 is None or d1 is None or d2 is None:
                continue

            # timestamp do item (em UTC); se não vier, usa agora
            ts_current = _parse_iso_ts(it.get("criado_em"))

            # trilateração fechada (sem mínimos quadrados)
            try:
                x_val = (d0 * d0 - d1 * d1 + kx * kx) / (2.0 * kx)
                y_val = (d0 * d0 - d2 * d2 + ky * ky) / (2.0 * ky)
            except ZeroDivisionError:
                continue

            # cálculo incremental de distância e tempo usando cache por tag
            dist_perc = None
            tempo_seg = None

            last = LAST_POS.get(tag_number)
            if last:
                last_x, last_y, last_ts = last
                # distância Euclidiana
                dx = float(x_val) - float(last_x)
                dy = float(y_val) - float(last_y)
                dist = math.sqrt(dx * dx + dy * dy)
                dist_perc = float(dist)

                # delta de tempo em segundos (inteiro)
                delta_sec = (ts_current - last_ts).total_seconds()
                # garanta não-negativo
                tempo_seg = int(delta_sec) if delta_sec >= 0 else 0

            # atualiza cache com a posição atual
            LAST_POS[tag_number] = (float(x_val), float(y_val), ts_current)

            # persiste registro processado
            rows.append(
                models.DistanciaProcessada(
                    tag_number=tag_number,
                    x=float(x_val),
                    y=float(y_val),
                    distancia_percorrida=dist_perc,   # None no primeiro ponto da tag
                    tempo_em_segundos=tempo_seg,      # None no primeiro ponto da tag
                    criado_em=ts_current.replace(tzinfo=None),  # DB costuma ser naive (UTC)
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
