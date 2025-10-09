# app/simulations/night_shift/simulation.py
import simpy
from .utils import make_rng, hhmm_dias
from .generators import generar_pallets_desde_cajas_dobles, construir_plan_desde_pallets
from .resources import Centro
from .metrics import _resumir_grua, calcular_resumen_vueltas, calcular_ice_mixto

def generar_json_vueltas_camiones(plan, centro):
    """Genera JSON con número de vuelta, camiones y cajas asignadas"""
    vueltas_data = {
        "vueltas": [],
        "info_reutilizacion": {
            "camiones_v1": [],
            "total_vueltas_por_camion": {}
        }
    }
    
    # Identificar camiones de V1 para tracking
    camiones_v1 = []
    if plan:
        primera_vuelta = plan[0]
        if primera_vuelta[0] == 1:  # Confirmar que es vuelta 1
            for asignacion in primera_vuelta[1]:
                camiones_v1.append(asignacion['camion_id'])
    
    vueltas_data["info_reutilizacion"]["camiones_v1"] = camiones_v1
    
    # Contar participaciones por camión
    conteo_participaciones = {}
    
    # Obtener todas las vueltas del plan
    for vuelta_num, asignaciones in plan:
        # Procesar eventos de esta vuelta
        eventos_vuelta = [e for e in centro.eventos if e["vuelta"] == vuelta_num]
        
        vuelta_info = {
            "numero_vuelta": vuelta_num,
            "tipo_operacion": "carga" if vuelta_num == 1 else "staging",
            "camiones": []
        }
        
        for evento in eventos_vuelta:
            camion_id = evento["camion_id"]
            
            # Contar participación
            if camion_id not in conteo_participaciones:
                conteo_participaciones[camion_id] = 0
            conteo_participaciones[camion_id] += 1
            
            camion_info = {
                "camion_id": camion_id,
                "cajas_asignadas": evento["cajas_pre"],
                "pre_asignados": evento["pre_asignados"],
            }
            vuelta_info["camiones"].append(camion_info)
        
        vueltas_data["vueltas"].append(vuelta_info)
    
    # Agregar información de reutilización
    vueltas_data["info_reutilizacion"]["total_vueltas_por_camion"] = conteo_participaciones
    
    # Estadísticas de reutilización
    camiones_reutilizados = [c for c, count in conteo_participaciones.items() if count > 1]
    vueltas_data["info_reutilizacion"]["estadisticas"] = {
        "total_camiones_unicos": len(conteo_participaciones),
        "camiones_reutilizados": len(camiones_reutilizados),
        "tasa_reutilizacion": len(camiones_reutilizados) / len(camiones_v1) * 100 if camiones_v1 else 0,
        "promedio_vueltas_por_camion": sum(conteo_participaciones.values()) / len(conteo_participaciones) if conteo_participaciones else 0
    }
    
    return vueltas_data


def simular_turno_prioridad_rng(total_cajas_facturadas, cajas_para_pick, cfg, seed=None):
    rng = make_rng(seed)
    env = simpy.Environment()

    pallets, resumen_pallets = generar_pallets_desde_cajas_dobles(total_cajas_facturadas, cajas_para_pick, cfg, rng)
    plan = construir_plan_desde_pallets(pallets, cfg, rng)

    # *** DEBUG: Mostrar plan completo ***
    print(f"[SIMULATION DEBUG] Plan generado con {len(plan)} vueltas:")
    for vuelta, asignaciones in plan:
        print(f"   Vuelta {vuelta}: {len(asignaciones)} camiones")

    pick_gate = {}
    for (vuelta, asign) in plan:
        pick_gate[vuelta] = {"target": len(asign), "count": 0, "event": env.event(), "done_time": None}

    pick_gate[0] = {"target": 0, "count": 0, "event": env.event(), "done_time": 0}
    pick_gate[0]["event"].succeed()

    # Calcular número total de camiones
    num_camiones_estimado = sum(len(asignaciones) for vuelta, asignaciones in plan)
    
    centro = Centro(env, cfg, pick_gate, rng, 
                   total_cajas_facturadas=total_cajas_facturadas,
                   num_camiones_estimado=num_camiones_estimado)

    # *** PROCESAR TODAS LAS VUELTAS ***
    for (vuelta, asignaciones) in plan:
        print(f"[SIMULATION DEBUG] Procesando vuelta {vuelta} con {len(asignaciones)} camiones")
        for camion_data in asignaciones:
            env.process(centro.procesa_camion_vuelta(vuelta, camion_data))

    env.run()

    resumen_por_vuelta = calcular_resumen_vueltas(plan, centro, cfg)
    total_fin = max(e["fin_min"] for e in centro.eventos) if centro.eventos else 0
    grua_metrics = _resumir_grua(centro, cfg, total_fin)
    ice_mixto = calcular_ice_mixto(centro, cfg)

    primera_vuelta_json = generar_json_vueltas_camiones(plan, centro)

    resultado_base =  {
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
        "centro_eventos": centro.eventos,  # eventos detallados (debug/inspección)
        
        # *** AGREGAR INFORMACIÓN ADICIONAL PARA DEBUGGING ***
        "grua_operaciones": centro.grua_ops,  # Operaciones detalladas de grúa
        "planificacion_detalle": plan,  # Plan original con asignaciones
        "pick_gates": pick_gate,  # Estados de los gates de pick
    }

    resultado_base.update(primera_vuelta_json)

    return resultado_base