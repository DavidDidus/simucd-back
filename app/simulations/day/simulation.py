# app/simulations/day/simulation.py
import simpy
from .config import get_day_config
from .centro import CentroDia
from .planning import construir_asignaciones_desde_estado, _resumen_pre_turno
from .reporting import imprimir_resumen_pre_turno
from .utils import hhmm_dias

def preview_turno_dia(estado_inicial_dia, seed=None):
    cfg = get_day_config()
    asignaciones = construir_asignaciones_desde_estado(estado_inicial_dia)
    resumen = _resumen_pre_turno(asignaciones)
    return {"cfg_dia": cfg, "asignaciones": asignaciones, "pre_turno": resumen}

def simular_turno_dia(estado_inicial_dia, seed=None):
    cfg = get_day_config()
    env = simpy.Environment()
    centro = CentroDia(env, cfg)

    asignaciones = construir_asignaciones_desde_estado(estado_inicial_dia)

    if cfg.get("debug", False):
        print("\n=== 🌙→☀️ ESTADO INICIAL DÍA (desde NOCHE) ===")
        print(f"Camiones en ruta (fin noche): {len(estado_inicial_dia.get('camiones_en_ruta', []))}")
        print(f"Lotes listos para carga: {len(estado_inicial_dia.get('pallets_listos_para_carga', []))}")
        print(f"Asignaciones construidas: {len(asignaciones)}")
        print("=============================================\n")

    resumen_pre = _resumen_pre_turno(asignaciones)
    imprimir_resumen_pre_turno(resumen_pre)

    resultado = centro.run(asignaciones, seed=seed, estado_inicial_dia=estado_inicial_dia)

    turno_ini = cfg.get("shift_start_min", 0)
    turno_fin_abs = cfg.get("shift_end_min", 0)
    return {
        **resultado,
        "asignaciones_entrada": asignaciones,
        "turno_inicio": hhmm_dias(turno_ini),
        "turno_fin_nominal": hhmm_dias(turno_fin_abs),
    }
