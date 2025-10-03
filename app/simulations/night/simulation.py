# app/simulations/night_shift/simulation.py
import simpy
from .utils import make_rng, hhmm_dias
from .generators import generar_pallets_desde_cajas_dobles, construir_plan_desde_pallets
from .resources import Centro
from .metrics import _resumir_grua, calcular_resumen_vueltas, calcular_ice_mixto

def simular_turno_prioridad_rng(total_cajas_facturadas, cajas_para_pick, cfg, seed=None):
    rng = make_rng(seed)                 # RNG local. seed=None => diferente cada vez.
    env = simpy.Environment()

    pallets, resumen_pallets = generar_pallets_desde_cajas_dobles(total_cajas_facturadas, cajas_para_pick, cfg, rng)
    plan = construir_plan_desde_pallets(pallets, cfg, rng)  # [(vuelta, [lista_pallets_camion,...])]

    pick_gate = {}
    for (vuelta, asign) in plan:
        pick_gate[vuelta] = {"target": len(asign), "count": 0, "event": env.event(), "done_time": None}

    pick_gate[0] = {"target": 0, "count": 0, "event": env.event(), "done_time": 0}
    pick_gate[0]["event"].succeed()

    centro = Centro(env, cfg, pick_gate, rng)

    for (vuelta, asignaciones) in plan:
        for cam_id, pallets_cam in enumerate(asignaciones, start=1):
            env.process(centro.procesa_camion_vuelta(vuelta, cam_id, pallets_cam))

    env.run()

    resumen_por_vuelta = calcular_resumen_vueltas(plan, centro, cfg)
    total_fin = max(e["fin_min"] for e in centro.eventos) if centro.eventos else 0
    grua_metrics = _resumir_grua(centro, cfg, total_fin)
    ice_mixto = calcular_ice_mixto(centro, cfg)

    return {
        "entradas_cajas": {
            "total_cajas_facturadas": int(total_cajas_facturadas),
            "cajas_para_pick": int(min(cajas_para_pick, total_cajas_facturadas)),
            "cajas_completas": int(max(total_cajas_facturadas - cajas_para_pick, 0)),
        },
        "pallets_pre": resumen_pallets,                     # cantidad de pallets generados por tipo
        "pallets_pre_total": len(pallets),
        "vueltas": len(plan),
        "turno_inicio": hhmm_dias(cfg["shift_start_min"]),
        "turno_fin_nominal": hhmm_dias(cfg["shift_end_min"]),
        "turno_fin_real": hhmm_dias(cfg["shift_start_min"] + total_fin),
        "overrun_total_min": max(0, total_fin - cfg["shift_end_min"]),
        "resumen_vueltas": resumen_por_vuelta,
        "grua": grua_metrics,
        "ice_mixto": ice_mixto,
    }