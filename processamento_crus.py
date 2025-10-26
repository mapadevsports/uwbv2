# processamento_crus.py (trilateração com 3 ou 4 âncoras + distância/tempo, robusto a -40)
from fastapi import APIRouter, Body, HTTPException
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timezone
import math

from db import SessionLocal
import models

router = APIRouter(prefix="/processamento-crus", tags=["Processamento de dados crus"])

# Cache em memória para última posição por tag:
# { "tag_number": (last_x, last_y, last_ts_utc) }
LAST_POS: Dict[str, Tuple[float, float, datetime]] = {}

# Valor especial: após offset = 40 cm, leituras "cruas=0" chegam como -40.
NO_READING_VALUE = -40.0
_EPS = 1e-9


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


def _valid_distance(d: Optional[float]) -> bool:
    """Valida distância: precisa ser número e > 0 e diferente de -40 (sem leitura)."""
    if d is None:
        return False
    if abs(d - NO_READING_VALUE) < 1e-9:  # -40 exatamente
        return False
    return d > 0.0


def _solve_xy_lsq(anchors: List[Tuple[float, float, float]]) -> Optional[Tuple[float, float]]:
    """
    Resolve posição (x,y) por linearização de círculos (mínimos quadrados).
    anchors: lista de (xi, yi, di) com di > 0, tamanho >= 3.
    Método: subtrai a última equação como referência (j) e resolve (A^T A) z = A^T b (z=[x,y]).
    Retorna (x,y) ou None se sistema for degenerado.
    """
    m = len(anchors)
    if m < 3:
        return None

    # escolha referência j (último)
    xj, yj, dj = anchors[-1]
    # constrói A (m-1 x 2) e b (m-1)
    a11 = a12 = a22 = 0.0
    b1 = b2 = 0.0
    for i in range(m - 1):
        xi, yi, di = anchors[i]
        ai1 = 2.0 * (xi - xj)
        ai2 = 2.0 * (yi - yj)
        bi = (di * di - dj * dj) - (xi * xi + yi * yi) + (xj * xj + yj * yj)

        # acumula A^T A e A^T b
        a11 += ai1 * ai1
        a12 += ai1 * ai2
        a22 += ai2 * ai2
        b1 += ai1 * bi
        b2 += ai2 * bi

    # resolve 2x2
    det = a11 * a22 - a12 * a12
    if abs(det) < _EPS:
        return None

    inv11 =  a22 / det
    inv12 = -a12 / det
    inv22 =  a11 / det

    x = inv11 * b1 + inv12 * b2
    y = inv12 * b1 + inv22 * b2
    return (x, y)


@router.post("/ingest")
def ingest_processados(payload: Dict[str, Any] = Body(..., example={
    "dados": [
        {
            "id": 123,
            "tag_number": "4",
            "da": [100, 110, 103, 0, 0, 0, 0, 0],  # pode ter 3 ou 4 âncoras válidas (A0..A3)
            "kx": 152.75,
            "ky": 101.3,
            "criado_em": "2025-10-11T20:49:21.900Z"
        }
    ]
})):
    """
    Recebe itens de `distancias_uwb` e grava em `distancias_processadas`:

      • Usa A0=(0,0), A1=(kx,0), A2=(0,ky), A3=(kx,ky)
      • Se houver >=3 âncoras válidas (d > 0 e d != -40), calcula (x, y) por LSQ.
      • Calcula distancia_percorrida e tempo_em_segundos com cache por tag.

    Observações:
      - Leituras exatamente -40 são ignoradas (é o "sem leitura" após offset).
      - Mantém compatível com entradas antigas (com ou sem A3).
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
            # dimensões do retângulo (distâncias entre âncoras)
            kx = _to_float_or_none(it.get("kx"))
            ky = _to_float_or_none(it.get("ky"))

            # validações mínimas de kx/ky
            if kx is None or ky is None or kx <= 0 or ky <= 0:
                continue

            # distâncias individuais (A0..A3). Podem não existir; tratamos como None.
            d0 = _to_float_or_none(da[0]) if len(da) > 0 else None
            d1 = _to_float_or_none(da[1]) if len(da) > 1 else None
            d2 = _to_float_or_none(da[2]) if len(da) > 2 else None
            d3 = _to_float_or_none(da[3]) if len(da) > 3 else None  # NOVO: âncora A3

            # filtra válidas (d > 0 e != -40)
            anchors_all: List[Tuple[float, float, Optional[float]]] = [
                (0.0, 0.0, d0),       # A0
                (kx, 0.0, d1),        # A1
                (0.0, ky, d2),        # A2
                (kx, ky, d3),         # A3 (opcional)
            ]
            anchors_valid: List[Tuple[float, float, float]] = [
                (xi, yi, float(di)) for (xi, yi, di) in anchors_all if _valid_distance(_to_float_or_none(di))
            ]

            if len(anchors_valid) < 3:
                # precisa de pelo menos 3 âncoras válidas
                continue

            # timestamp do item (em UTC); se não vier, usa agora
            ts_current = _parse_iso_ts(it.get("criado_em"))

            # resolve posição por LSQ (3 ou 4 âncoras)
            xy = _solve_xy_lsq(anchors_valid)
            if xy is None:
                # sistema degenerado (raro): pula
                continue

            x_val, y_val = float(xy[0]), float(xy[1])

            # cálculo incremental de distância e tempo usando cache por tag
            dist_perc = None
            tempo_seg = None
            last = LAST_POS.get(tag_number)
            if last:
                last_x, last_y, last_ts = last
                dx = x_val - float(last_x)
                dy = y_val - float(last_y)
                dist = math.hypot(dx, dy)
                dist_perc = float(dist)

                delta_sec = (ts_current - last_ts).total_seconds()
                tempo_seg = int(delta_sec) if delta_sec >= 0 else 0

            # atualiza cache com a posição atual
            LAST_POS[tag_number] = (x_val, y_val, ts_current)

            # persiste registro processado
            rows.append(
                models.DistanciaProcessada(
                    tag_number=tag_number,
                    x=x_val,
                    y=y_val,
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
