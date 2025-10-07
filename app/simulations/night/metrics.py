# app/simulations/night_shift/metrics.py
from collections import defaultdict
from .utils import hhmm_dias

def _resumir_grua(centro, cfg, total_fin):
    ops = centro.grua_ops
    by_vuelta = defaultdict(list)
    by_label = defaultdict(list)
    for o in ops:
        by_vuelta[o["vuelta"]].append(o)
        by_label[o["label"]].append(o)

    def pack(lst):
        if not lst:
            return {"ops": 0, "total_wait_min": 0, "mean_wait_min": 0, "max_wait_min": 0,
                    "total_hold_min": 0, "mean_hold_min": 0}
        waits = [x["wait"] for x in lst]
        holds = [x["hold"] for x in lst]
        return {
            "ops": len(lst),
            "total_wait_min": sum(waits),
            "mean_wait_min": (sum(waits)/len(waits) if waits else 0),
            "max_wait_min": (max(waits) if waits else 0),
            "total_hold_min": sum(holds),
            "mean_hold_min": (sum(holds)/len(holds) if holds else 0),
        }

    por_vuelta = []
    for v in sorted(by_vuelta):
        rec = pack(by_vuelta[v]); rec["vuelta"] = v
        por_vuelta.append(rec)

    por_label = {lbl: pack(lst) for lbl, lst in by_label.items()}

    total_hold = sum(o["hold"] for o in ops)
    horizon = max(total_fin, 1e-9)
    cap_total = cfg.get("cap_gruero", 4)
    util = total_hold / (cap_total * horizon)

    overall = {
        "ops": len(ops),
        "total_hold_min": total_hold,
        "total_wait_min": sum(o["wait"] for o in ops),
        "mean_wait_min": (sum(o["wait"] for o in ops)/len(ops) if ops else 0),
        "utilizacion_prom": util
    }
    return {"overall": overall, "por_vuelta": por_vuelta, "por_label": por_label}

def calcular_resumen_vueltas(plan, centro, cfg):
    resumen_por_vuelta = []
    shift_end = cfg["shift_end_min"]

    for (vuelta, asignaciones) in plan:
        items = [e for e in centro.eventos if e["vuelta"] == vuelta]
        if not items:
            continue

        inicio_min   = min(e["inicio_min"] for e in items)              # inicio real (tras gate)
        fin_oper_min = max(e["fin_min"]    for e in items)              # fin operativo (incluye acomodo/carga)
        pick_fin_min = centro.pick_gate[vuelta]["done_time"]            # fin de PICK (gate liberado)

        fin_resumen_min = pick_fin_min if pick_fin_min is not None else fin_oper_min

        resumen_por_vuelta.append({
            "vuelta": vuelta,
            "camiones_en_vuelta": len(items),

            "inicio_hhmm": hhmm_dias(cfg["shift_start_min"] + inicio_min),
            "fin_hhmm":    hhmm_dias(cfg["shift_start_min"] + fin_resumen_min),
            "duracion_vuelta_min": fin_resumen_min - inicio_min,
            "overrun_min": max(0, fin_resumen_min - shift_end),

            "pick_fin_hhmm": hhmm_dias(cfg["shift_start_min"] + pick_fin_min) if pick_fin_min is not None else None,
            "fin_operativo_hhmm": hhmm_dias(cfg["shift_start_min"] + fin_oper_min),
            "duracion_operativa_min": fin_oper_min - inicio_min,

            "pre_quemados_pallets": sum(e["pre_asignados"] for e in items),
            "pre_quemados_cajas":   sum(e["cajas_pre"]      for e in items),
            "post_cargados_pallets": sum(e["post_cargados"] for e in items),  # solo v1
            "fusionados":            sum(e["fusionados"]    for e in items),  # solo v1
            "modo": ("carga" if vuelta == 1 else "staging")
        })
    
    return resumen_por_vuelta

def calcular_ice_mixto(centro, cfg):
    pickers = cfg.get("cap_picker", 0)
    horas_eff = cfg.get("horas_efectivas_ice", 7.1)
    total_cajas_pickeadas_mixtas = sum(e.get("cajas_pick_mixto", 0) for e in centro.eventos)
    ice_val_mixto = (total_cajas_pickeadas_mixtas / pickers / horas_eff) if (pickers and horas_eff) else None
    
    return {
        "total_cajas_pickeadas_mixtas": total_cajas_pickeadas_mixtas,
        "pickers": pickers,
        "horas_efectivas": horas_eff,
        "valor": ice_val_mixto
    }
    

def analizar_capacidades_camiones(centro_eventos):
    """
    Analiza el uso de capacidades de los camiones
    """
    analisis = {
        'por_vuelta': {},
        'limitaciones': {'cajas': 0, 'pallets': 0, 'ninguno': 0},
        'utilizacion_promedio': {'pallets': 0, 'cajas': 0},
        'estadisticas': {}
    }
    
    eventos_con_capacidad = [e for e in centro_eventos if 'capacidad_pallets_disponible' in e]
    
    if not eventos_con_capacidad:
        return analisis
    
    # Análisis por vuelta
    for evento in eventos_con_capacidad:
        vuelta = evento['vuelta']
        if vuelta not in analisis['por_vuelta']:
            analisis['por_vuelta'][vuelta] = {
                'camiones': 0,
                'util_pallets_total': 0,
                'util_cajas_total': 0,
                'capacidades_pallets': [],
                'capacidades_cajas': []
            }
        
        v_data = analisis['por_vuelta'][vuelta]
        v_data['camiones'] += 1
        v_data['util_pallets_total'] += evento.get('utilizacion_pallets_pct', 0)
        v_data['util_cajas_total'] += evento.get('utilizacion_cajas_pct', 0)
        v_data['capacidades_pallets'].append(evento['capacidad_pallets_disponible'])
        v_data['capacidades_cajas'].append(evento['capacidad_cajas_disponible'])
        
        # Contar limitaciones
        limitado_por = evento.get('limitado_por', 'ninguno')
        if limitado_por in analisis['limitaciones']:
            analisis['limitaciones'][limitado_por] += 1
    
    # Calcular promedios
    for vuelta, data in analisis['por_vuelta'].items():
        if data['camiones'] > 0:
            data['util_pallets_prom'] = data['util_pallets_total'] / data['camiones']
            data['util_cajas_prom'] = data['util_cajas_total'] / data['camiones']
            data['capacidad_pallets_prom'] = sum(data['capacidades_pallets']) / len(data['capacidades_pallets'])
            data['capacidad_cajas_prom'] = sum(data['capacidades_cajas']) / len(data['capacidades_cajas'])
    
    # Estadísticas generales
    total_camiones = len(eventos_con_capacidad)
    if total_camiones > 0:
        analisis['utilizacion_promedio']['pallets'] = sum(e.get('utilizacion_pallets_pct', 0) for e in eventos_con_capacidad) / total_camiones
        analisis['utilizacion_promedio']['cajas'] = sum(e.get('utilizacion_cajas_pct', 0) for e in eventos_con_capacidad) / total_camiones
    
    return analisis

def obtener_top_camiones(centro_eventos, criterio='cajas', top_n=5):
    """
    Obtiene los top N camiones según el criterio especificado
    """
    if criterio == 'cajas':
        key_func = lambda x: x.get('cajas_pre', 0)
    elif criterio == 'pallets':
        key_func = lambda x: x.get('post_cargados', x.get('pre_asignados', 0))
    elif criterio == 'tiempo':
        key_func = lambda x: x.get('tiempo_min', 0)
    elif criterio == 'utilizacion_cajas':
        key_func = lambda x: x.get('utilizacion_cajas_pct', 0)
    elif criterio == 'utilizacion_pallets':
        key_func = lambda x: x.get('utilizacion_pallets_pct', 0)
    else:
        key_func = lambda x: x.get('cajas_pre', 0)
    
    return sorted(centro_eventos, key=key_func, reverse=True)[:top_n]