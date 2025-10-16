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

    almuerzo_inicio = cfg.get("almuerzo_inicio_min", 150)
    pausa_almuerzo = 30

    for (vuelta, _) in plan:
        items = [e for e in centro.eventos if e["vuelta"] == vuelta]
        if not items:
            continue

        inicio_min_bruto   = min(e["inicio_min"] for e in items)
        fin_oper_min_bruto = max(e["fin_min"] for e in items)
        pick_fin_min_bruto = centro.pick_gate[vuelta]["done_time"]

        inicio_min = inicio_min_bruto + (pausa_almuerzo if inicio_min_bruto >= almuerzo_inicio else 0)
        fin_oper_min = fin_oper_min_bruto + (pausa_almuerzo if fin_oper_min_bruto >= almuerzo_inicio else 0)
        if pick_fin_min_bruto is not None:
            pick_fin_min = pick_fin_min_bruto + (pausa_almuerzo if pick_fin_min_bruto >= almuerzo_inicio else 0)
        else:
            pick_fin_min = None

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
            "pre_quemados_cajas":   sum(e["cajas_pre"] for e in items),
            "post_cargados_pallets": sum(e["post_cargados"] for e in items),
            "fusionados":            sum(e["fusionados"] for e in items),
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
