# app/simulations/day/reporting.py
def imprimir_resumen_pre_turno(resumen):
    for r in resumen:
        print(f"\n🔁 Vuelta {r['vuelta']} — camiones={r['total_camiones']} | "
              f"pallets={r['total_pallets']} | cajas={r['total_cajas']}")
        for d in r["detalle"]:
            print(f"  · {d['camion_id']:>6}  pallets={d['pallets']:>2}  cajas={d['cajas']}")
