# app/simulations/day/utils.py
import math
from ..night.utils import hhmm_dias
from ..night.rng import U_rng

# ---------------------------------------------------------------------------
# Llegadas y retornos: Weibull desplazada (alpha, beta, gamma), en minutos.
# Se usa tanto para la ETA inicial de V2 como para cada retorno entre vueltas.
# ---------------------------------------------------------------------------

def _sample_weibull_shifted(rng, alpha: float, beta: float, gamma: float) -> float:
    """
    Muestra T = gamma + Weibull(alpha, beta), en minutos.
    Parametrización: F(t) = 1 - exp(-(t/beta)^alpha) para t>=0 (luego se desplaza con gamma).
    """
    # Evita extremos 0/1 en la inversa
    u = U_rng(rng, 1e-12, 1.0 - 1e-12)
    # Inversa Weibull (escala=beta, forma=alpha)
    w = beta * (-math.log(1.0 - u)) ** (1.0 / alpha)
    return gamma + max(0.0, w)


def calcular_tiempo_retorno(offset_idx, cfg, rng) -> float:
    """
    Devuelve un tiempo de viaje (min) para llegada/retorno de camión.
    Lee parámetros desde cfg["retorno_weibull"].
    'offset_idx' se ignora (queda para futuras estratificaciones).
    """
    par = cfg.get("retorno_weibull", {}) or {}
    # Acepta 'alpha' o 'alfa' por compatibilidad
    alpha = float(par.get("alpha", par.get("alfa", 2.1967)))
    beta  = float(par.get("beta", 343.6))
    gamma = float(par.get("gamma", 30.126))
    t = _sample_weibull_shifted(rng, alpha, beta, gamma)
    # Garantiza no-negatividad
    return max(0.0, t)


# ---------------------------------------------------------------------------
# Presentación simple del cronograma del día (para reportes/tableros)
# ---------------------------------------------------------------------------
def formatear_cronograma_dia(eventos):
    """
    Convierte la lista de 'eventos' del centro en una lista de dicts con claves:
    'hora_inicio', 'hora_fin', 'camion', 'pallets', 'cajas', 'duracion_min'.
    Maneja varias posibles ubicaciones de los timestamps (nivel superior o metadata).
    """
    salida = []
    for ev in eventos or []:
        meta = ev.get("metadata", {}) if isinstance(ev, dict) else {}
        # buscar valores de inicio/fin en varias claves posibles
        def _buscar(keys, fuente):
            for k in keys:
                if k in fuente:
                    return fuente[k]
            return None

        start = _buscar(("hora_inicio", "inicio_min", "inicio", "start", "t_start"), ev) or \
                _buscar(("hora_inicio", "inicio_min", "inicio", "start", "t_start"), meta)
        end = _buscar(("hora_fin", "fin_min", "fin", "end", "t_end"), ev) or \
              _buscar(("hora_fin", "fin_min", "fin", "end", "t_end"), meta)

        # si no tenemos ambos tiempos, intentar inferir duración si está disponible
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

        # formato horario legible (siempre que start_min/end_min no sean None)
        hora_inicio = hhmm_dias(480 + start_min) if start_min is not None else ""
        hora_fin = hhmm_dias(480 + end_min) if end_min is not None else ""
        dur = (end_min - start_min) if (start_min is not None and end_min is not None) else None

        # camion
        camion = _buscar(("camion", "camion_id", "truck"), ev) or _buscar(("camion", "camion_id", "truck"), meta) or ""

        # pallets: puede venir como número o como lista en metadata
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

        # cajas: buscar campo directo o sumar si hay lista de pallets con 'cajas'
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
            # opcional: mantener valores numéricos para ordenar
            "_start_min": start_min if start_min is not None else float("inf")
        })

    # ordenar por inicio y eliminar clave interna
    salida = sorted(salida, key=lambda x: x["_start_min"])
    for r in salida:
        r.pop("_start_min", None)
    return salida