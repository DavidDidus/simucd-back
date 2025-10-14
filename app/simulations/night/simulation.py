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

            es_reutilizado = camion_id in camiones_v1 and vuelta_num > 1

            max_vuelta = max(v for v, _ in plan) if plan else 0
            
            camion_info = {
                "camion_id": camion_id,
                "cajas_asignadas": evento["cajas_pre"],
                "pre_asignados": evento["pre_asignados"],
                "pallets_detalle": evento["cajas_pickeadas_detalle"],

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

def generar_estado_inicial_dia(plan, centro):

    estado_dia = {
        "camiones_en_ruta": [],
        "pallets_listos_para_carga": [],
        "cronograma_retornos": [],
        "vueltas_pendientes": []
    }

    if not plan:
        return estado_dia
    
    primera_vuelta = None
    for vuelta, asignaciones in plan:
        if vuelta == 1:
            primera_vuelta = asignaciones
            break

    if primera_vuelta:
        for asignacion in primera_vuelta:
            eventos_camion = [e for e in centro.eventos if e["camion_id"] == asignacion["camion_id"] and e["vuelta"] == 1]
            if eventos_camion:
                evento = eventos_camion[0]
                estado_dia["camiones_en_ruta"].append({
                    "camion_id": evento["camion_id"],
                    "salio_noche_fin": evento["fin_hhmm"],
                    "cajas_cargadas_v1": evento["cajas_pre"],
                    "tiempo_estimado_retorno_horas": 8,  # Estimación de tiempo de ruta
                    "proximo_vuelta_asignada": None  # Se determinará cuando regrese
                })

    # 2. Identificar pallets de vueltas 2+ que ya están preparados
    vueltas_staging = [v for v in plan if v[0] > 1]
    
    for vuelta_num, asignaciones in vueltas_staging:
        for asignacion in asignaciones:
            eventos_camion = [e for e in centro.eventos if e["camion_id"] == asignacion['camion_id'] and e["vuelta"] == vuelta_num]
            if eventos_camion:
                evento = eventos_camion[0]
                
                # Los pallets ya están preparados desde la noche
                pallets_preparados = {
                    "vuelta_origen": vuelta_num,
                    "camion_asignado": evento["camion_id"],
                    "pallets_mixtos": evento["cajas_pickeadas_detalle"]["pallets_mixtos"],
                    "pallets_completos": evento["cajas_pickeadas_detalle"]["pallets_completos"],
                    "total_cajas": evento["cajas_pre"],
                    "estado": "listo_para_carga",  # Ya fueron procesados en la noche
                    "preparado_noche_fin": evento["fin_hhmm"]
                }
                
                estado_dia["pallets_listos_para_carga"].append(pallets_preparados)
    
    # 3. Crear cronograma de vueltas para el día
    for vuelta_num, asignaciones in vueltas_staging:
        vuelta_dia = {
            "numero_vuelta_original": vuelta_num,
            "tipo": "carga_dia",  # Se carga durante el día con pallets ya preparados
            "camiones_involucrados": [a['camion_id'] for a in asignaciones],
            "estado": "esperando_retorno_camiones",
            "pallets_disponibles": True,  # Ya están preparados desde la noche
            "dependencias": "camiones_regresen_de_ruta"
        }
        
        estado_dia["vueltas_pendientes"].append(vuelta_dia)
    
    # 4. Cronograma estimado de retornos
    hora_base_retorno = 8  # 8:00 AM - cuando empiezan a regresar los camiones
    for i, camion in enumerate(estado_dia["camiones_en_ruta"]):
        retorno_estimado = {
            "camion_id": camion["camion_id"],
            "hora_retorno_estimada": f"{hora_base_retorno + (i * 0.5):.1f}:00",  # Retornos escalonados cada 30 min
            "siguiente_carga_disponible": len(estado_dia["pallets_listos_para_carga"]) > i,
            "vuelta_asignada": vueltas_staging[i % len(vueltas_staging)][0] if vueltas_staging else None
        }
        estado_dia["cronograma_retornos"].append(retorno_estimado)
    
    return estado_dia
    
def simular_turno_prioridad_rng(total_cajas_facturadas, cajas_para_pick, cfg, seed=None):
    rng = make_rng(seed)
    env = simpy.Environment()

    pallets, resumen_pallets = generar_pallets_desde_cajas_dobles(total_cajas_facturadas, cajas_para_pick, cfg, rng)
    plan = construir_plan_desde_pallets(pallets, cfg, rng)

    # *** DEBUG: Mostrar plan completo con reutilización ***
    print(f"Plan generado con {len(plan)} vueltas:")
    camiones_v1 = []
    for vuelta, asignaciones in plan:
        camiones_vuelta = [a['camion_id'] for a in asignaciones]
        print(f"   Vuelta {vuelta}: {len(asignaciones)} camiones - {camiones_vuelta}")
        
        if vuelta == 1:
            camiones_v1 = camiones_vuelta
        else:
            # Mostrar cuáles son reutilizados
            reutilizados = [c for c in camiones_vuelta if c in camiones_v1]
            nuevos = [c for c in camiones_vuelta if c not in camiones_v1]
            print(f"      - Reutilizados de V1: {reutilizados}")
            if nuevos:
                print(f"      - Nuevos camiones: {nuevos}")

    pick_gate = {}
    for (vuelta, asign) in plan:
        pick_gate[vuelta] = {"target": len(asign), "count": 0, "event": env.event(), "done_time": None}

    pick_gate[0] = {"target": 0, "count": 0, "event": env.event(), "done_time": 0}
    pick_gate[0]["event"].succeed()

    # Calcular número total de camiones únicos
    camiones_unicos = set()
    for vuelta, asignaciones in plan:
        for asignacion in asignaciones:
            camiones_unicos.add(asignacion['camion_id'])
    
    num_camiones_estimado = len(camiones_unicos)
    
    centro = Centro(env, cfg, pick_gate, rng, 
                   total_cajas_facturadas=total_cajas_facturadas,
                   num_camiones_estimado=num_camiones_estimado)

    # *** PROCESAR TODAS LAS VUELTAS ***
    for (vuelta, asignaciones) in plan:
        print(f"Procesando vuelta {vuelta} con {len(asignaciones)} camiones")
        for camion_data in asignaciones:
            env.process(centro.procesa_camion_vuelta(vuelta, camion_data))

    env.run()

    resumen_por_vuelta = calcular_resumen_vueltas(plan, centro, cfg)
    total_fin = max(e["fin_min"] for e in centro.eventos) if centro.eventos else 0
    grua_metrics = _resumir_grua(centro, cfg, total_fin)
    ice_mixto = calcular_ice_mixto(centro, cfg)

    # *** GENERAR JSON DE VUELTAS CON INFORMACIÓN DE REUTILIZACIÓN ***
    vueltas_camiones_json = generar_json_vueltas_camiones(plan, centro)
    
    # *** GENERAR ESTADO INICIAL PARA EL DÍA ***
    estado_inicial_dia = generar_estado_inicial_dia(plan, centro)

    resultado_base = {
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
        "resumen_vueltas": resumen_por_vuelta,
        "grua": grua_metrics,
        "ice_mixto": ice_mixto,
        "centro_eventos": centro.eventos,
        "grua_operaciones": centro.grua_ops,
        "planificacion_detalle": plan,
        "pick_gates": pick_gate,
        
        # *** INFORMACIÓN PARA EL TURNO DEL DÍA ***
        "estado_inicial_dia": estado_inicial_dia
    }

    # *** COMBINAR CON JSON DE VUELTAS Y CAMIONES ***
    resultado_base.update(vueltas_camiones_json)

    return resultado_base