# app/simulations/day/utils.py
import math
from ..night.utils import hhmm_dias
from ..night.rng import U_rng
from typing import Optional

# ---------------------------------------------------------------------------
# Weibull desplazada (alpha, beta, gamma), en minutos/valor continuo.
# ---------------------------------------------------------------------------

def _sample_weibull_shifted(rng, alpha: float, beta: float, gamma: float) -> float:
    """
    Muestra T = gamma + Weibull(alpha, beta).
    Parametrización: F(t) = 1 - exp(-(t/beta)^alpha) para t>=0 (luego se desplaza con gamma).
    """
    # u en (0,1) para evitar extremos
    u = U_rng(rng, 1e-12, 1.0 - 1e-12)
    w = beta * (-math.log(1.0 - u)) ** (1.0 / alpha)
    return gamma + max(0.0, w)

# (compat) interarribo T1 (ya no lo usamos, pero lo dejamos disponible)
def sample_interarribo_t1(rng, params: dict) -> float:
    alpha = params.get("alpha", params.get("alfa"))
    beta  = params.get("beta")
    gamma = params.get("gamma", 0.0)
    if alpha is None or beta is None:
        raise ValueError("Faltan parámetros (alpha/beta) para T1 Weibull")
    return _sample_weibull_shifted(rng, float(alpha), float(beta), float(gamma))

# --- NUEVO: cantidad de camiones T1 que llegan en el día ---------------------
def sample_num_camiones_t1_dia(rng, params: dict, max_camiones: Optional[int]  = None) -> int:
    """
    Usa la Weibull desplazada para muestrear un valor continuo y lo redondea
    a un entero >=0. Se puede acotar por 'max_camiones' (p.ej. 10).
    """
    alpha = params.get("alpha", params.get("alfa"))
    beta  = params.get("beta")
    gamma = params.get("gamma", 0.0)
    if alpha is None or beta is None:
        raise ValueError("Faltan parámetros (alpha/beta) para T1 Weibull")

    val = _sample_weibull_shifted(rng, float(alpha), float(beta), float(gamma))
    n = int(round(val))
    if n < 0:
        n = 0
    if max_camiones is not None:
        n = min(n, int(max_camiones))
    return n


# ---------------------------------------------------------------------------
# Presentación simple del cronograma del día (para reportes/tableros)
# ---------------------------------------------------------------------------
def formatear_cronograma_dia(eventos):
    salida = []
    for ev in eventos or []:
        meta = ev.get("metadata", {}) if isinstance(ev, dict) else {}

        def _buscar(keys, fuente):
            for k in keys:
                if k in fuente:
                    return fuente[k]
            return None

        start = _buscar(("hora_inicio", "inicio_min", "inicio", "start", "t_start"), ev) or \
                _buscar(("hora_inicio", "inicio_min", "inicio", "start", "t_start"), meta)
        end = _buscar(("hora_fin", "fin_min", "fin", "end", "t_end"), ev) or \
              _buscar(("hora_fin", "fin_min", "fin", "end", "t_end"), meta)

        if start is None and end is None:
            continue

        try:
            start_min = float(start) if start is not None else None
        except Exception:
            start_min = None
        try:
            end_min = float(end) if end is not None else None
        except Exception:
            end_min = None

        hora_inicio = hhmm_dias(480 + start_min) if start_min is not None else ""
        hora_fin = hhmm_dias(480 + end_min) if end_min is not None else ""
        dur = (end_min - start_min) if (start_min is not None and end_min is not None) else None

        camion = _buscar(("camion", "camion_id", "truck"), ev) or _buscar(("camion", "camion_id", "truck"), meta) or ""

        pallets_val = _buscar(("pallets", "num_pallets"), ev)
        if pallets_val is None:
            pallets_val = _buscar(("pallets", "pallets_finales", "pallets_asignados"), meta)
            if isinstance(pallets_val, (list, tuple)):
                pallets_count = len(pallets_val)
            elif isinstance(pallets_val, (int, float)):
                pallets_count = int(pallets_val)
            else:
                pallets_count = 0
        else:
            pallets_count = int(pallets_val) if isinstance(pallets_val, (int, float)) else 0

        cajas = _buscar(("cajas", "total_cajas", "total"), ev) or _buscar(("cajas", "total_cajas", "total"), meta)
        if cajas is None:
            pallets_list = _buscar(("pallets", "pallets_finales", "pallets_asignados"), meta)
            if isinstance(pallets_list, (list, tuple)):
                try:
                    cajas = sum(int(p.get("cajas", 0)) for p in pallets_list if isinstance(p, dict))
                except Exception:
                    cajas = 0
            else:
                cajas = 0
        try:
            cajas = int(cajas)
        except Exception:
            cajas = 0

        salida.append({
            "hora_inicio": hora_inicio,
            "hora_fin": hora_fin,
            "camion": camion,
            "pallets": pallets_count,
            "cajas": cajas,
            "duracion_min": float(dur) if (dur is not None) else 0.0,
            "_start_min": start_min if start_min is not None else float("inf")
        })

    salida = sorted(salida, key=lambda x: x["_start_min"])
    for r in salida:
        r.pop("_start_min", None)
    return salida
