# app/simulations/day/metrics.py
from ..night.metrics import calcular_ocupacion_recursos as _calc

def calcular_ocupacion_recursos(centro, cfg, tiempo_total_turno):
    """
    Envuelve el cálculo de noche y le inyecta los contadores propios del día
    (tiempo_activo y operaciones) para cada recurso.
    """
    base = _calc(centro, cfg, tiempo_total_turno)  # conserva % ocupación

    # Inyectar tiempos y operaciones desde centro.metricas_recursos (día)
    mr = getattr(centro, "metricas_recursos", {}) or {}
    for k, v in mr.items():
        b = base.setdefault(k, {})
        b["tiempo_activo"] = b.get("tiempo_activo", 0) + float(v.get("tiempo_activo", 0) or 0.0)
        b["operaciones"]   = b.get("operaciones",   0) + int(v.get("operaciones", 0) or 0)

    # Asegurar el nodo "resumen" aunque no lo uses
    base.setdefault("resumen", base.get("resumen", {}))
    return base

__all__ = ["calcular_ocupacion_recursos"]
