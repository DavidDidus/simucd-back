# app/simulations/night_shift/simulation.py
import simpy
from .rng import make_rng
from .utils import hhmm_dias
from .planning import generar_pallets_desde_cajas_dobles, construir_plan_desde_pallets
from .centro import Centro
from .metrics import _resumir_grua, calcular_resumen_vueltas, calcular_ice_mixto, calcular_ocupacion_recursos
from .reporting import generar_json_vueltas_camiones, generar_estado_inicial_dia

def simular_turno_prioridad_rng(total_cajas_facturadas, cajas_para_pick, cfg, seed=None):
    rng = make_rng(seed)
    env = simpy.Environment()

    pallets, resumen_pallets = generar_pallets_desde_cajas_dobles(total_cajas_facturadas, cajas_para_pick, cfg, rng)
    plan = construir_plan_desde_pallets(pallets, cfg, rng)

    # Gates de PICK por vuelta
    pick_gate = {}
    for (vuelta, asign) in plan:
        pick_gate[vuelta] = {"target": len(asign), "count": 0, "event": env.event(), "done_time": None}
    pick_gate[0] = {"target": 0, "count": 0, "event": env.event(), "done_time": 0}
    pick_gate[0]["event"].succeed()

    # Camiones únicos estimados
    camiones_unicos = {a["camion_id"] for (_, asign) in plan for a in asign}
    centro = Centro(env, cfg, pick_gate, rng,
                    total_cajas_facturadas=total_cajas_facturadas,
                    num_camiones_estimado=len(camiones_unicos))

    # Lanzar procesos por vuelta
    for (vuelta, asignaciones) in plan:
        for camion_data in asignaciones:
            env.process(centro.procesa_camion_vuelta(vuelta, camion_data))

    env.run()

    total_fin = max((e["fin_min"] for e in centro.eventos), default=0)
    resumen_por_vuelta = calcular_resumen_vueltas(plan, centro, cfg)
    grua_metrics = _resumir_grua(centro, cfg, total_fin)
    ice_mixto = calcular_ice_mixto(centro, cfg)

    # Reportes
    vueltas_camiones_json = generar_json_vueltas_camiones(plan, centro)
    estado_inicial_dia = generar_estado_inicial_dia(plan, centro)

    ocupacion = calcular_ocupacion_recursos(centro, cfg, total_fin)

    linea_tiempo_ordenada = sorted(centro.linea_tiempo, key=lambda e: e["tiempo_min"])

    resultado = {
        "entradas_cajas": {
            "total_cajas_facturadas": int(total_cajas_facturadas),
            "cajas_para_pick": int(min(cajas_para_pick, total_cajas_facturadas)),
            "cajas_completas": int(max(total_cajas_facturadas - cajas_para_pick, 0)),
        },
        "pallets_pre": resumen_pallets,
        "pallets_pre_total": len(pallets),
        "vueltas": len(plan),
        "turno_inicio": hhmm_dias(cfg["shift_start_min"]),
        "turno_fin_nominal": hhmm_dias(cfg["shift_end_min"]),
        "turno_fin_real": hhmm_dias(cfg["shift_start_min"] + total_fin),
        "overrun_total_min": max(0, total_fin - cfg["shift_end_min"]),
        "timeline": linea_tiempo_ordenada,
        "resumen_vueltas": resumen_por_vuelta,
        "grua": grua_metrics,
        "ice_mixto": ice_mixto,
        "ocupacion_recursos": ocupacion,
        "centro_eventos": centro.eventos,
        "grua_operaciones": centro.grua_ops,
        "planificacion_detalle": plan,
        "pick_gates": pick_gate,
        "estado_inicial_dia": estado_inicial_dia,
    }
    print(resultado["ocupacion_recursos"])

    resultado.update(vueltas_camiones_json)
    return resultado
