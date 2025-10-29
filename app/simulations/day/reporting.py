# app/simulations/day/reporting.py
def imprimir_resumen_pre_turno(resumen):
    for r in resumen:
        print(f"\n🔁 Vuelta {r['vuelta']} — camiones={r['total_camiones']} | "
              f"pallets={r['total_pallets']} | cajas={r['total_cajas']}")
        for d in r["detalle"]:
            print(f"  · {d['camion_id']:>6}  pallets={d['pallets']:>2}  cajas={d['cajas']}")

def _fmt_hhmm(abs_min: int) -> str:
    h = (abs_min // 60) % 24
    m = abs_min % 60
    return f"{h:02d}:{m:02d}"

def imprimir_ocupacion_turnos_dia(ocupacion: dict, cfg: dict):
    """
    Imprime ocupación por recurso + detalle de los *dos turnos del día*.
    """
    base_abs = int(cfg.get("shift_start_min", 0))
    print("Ocupación recursos (día):")
    for k, v in ocupacion.items():
        if k == "resumen":
            continue
        pct_total = v.get("porcentaje_ocupacion", 0.0)
        t_act = v.get("tiempo_activo", 0.0)
        ops   = v.get("operaciones", 0)
        print(f" - {k:14s} -> {pct_total:5.1f}%  activo={t_act:.1f} min  ops={ops}")
        for i, w in enumerate(v.get("por_turno_dia", [])[:2], start=1):
            s_abs = base_abs + int(w.get("inicio_min", 0))
            e_abs = base_abs + int(w.get("fin_min", 0))
            pct_w = w.get("porcentaje_ocupacion", 0.0)
            t_w   = w.get("tiempo_activo", 0.0)
            den_w = w.get("cap_x_tiempo", 0.0)
            print(f"     T{i} [{_fmt_hhmm(s_abs)}–{_fmt_hhmm(e_abs)}]  {pct_w:5.1f}%  activo={t_w:.1f} min  denom={den_w:.1f}")