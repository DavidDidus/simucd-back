import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.simulations.complete_cycle import simular_ciclo_completo_24h
from app.simulations.analysis_helpers import (
    resumen_kpis_dia, resumen_kpis_noche, diagnostico_bottleneck
)
from app.simulations.day.reporting import imprimir_ocupacion_turnos_dia

def test_ciclo_completo():
    # Puedes ajustar dotación del día aquí:

    resultado = simular_ciclo_completo_24h(
        total_cajas_facturadas=20000,
        cajas_para_pick=19000,
        seed=None,
    )

    noche, dia = resultado["turno_noche"], resultado["turno_dia"]

    print("Vueltas:", noche.get("num_vueltas", 0), "noche +", dia.get("num_vueltas", 0), "día")

    # --- Continuidad Noche→Día
    cam_v1 = set(noche.get("info_reutilizacion", {}).get("camiones_v1", []))
    cam_dia = {c["camion_id"] for c in dia.get("nueva_salida_camiones", [])}
    print("\n🧩 CONTINUIDAD NOCHE→DÍA")
    print("V1 noche:", sorted(cam_v1))
    print("V2 día :", sorted(cam_dia))
    print("Día    :", sorted(cam_dia))
    

    # --- KPIs
    print("\n🌙 KPIs NOCHE")
    for k, v in resumen_kpis_noche(noche).items():
        print(f"- {k}: {v}")

    print("\n☀️  KPIs DÍA")
    for k, v in resumen_kpis_dia(dia).items():
        print(f"- {k}: {v:.2f}" if isinstance(v, float) else f"- {k}: {v}")

    # --- Cronograma día
    print("\n🗓️  CRONOGRAMA DÍA (ordenado por inicio)")
    for r in dia.get("cronograma_dia", []):
        print(f"{r['hora_inicio']}–{r['hora_fin']} | camión {r['camion']:>6} | "
              f"pallets={r['pallets']:>2} | cajas={r['cajas']:>4} | "
              f"dur={r['duracion_min']:.1f} min")

    # --- Diagnóstico rápido de cuello de botella
    print("\n🔎 Diagnóstico:", diagnostico_bottleneck(dia))

    cfg_dia = (
        dia.get("cfg") or                # si el turno día ya trae su cfg
        resultado.get("cfg_dia") or      # si el wrapper del ciclo devuelve cfg_dia
        resultado.get("cfg") or          # último recurso: cfg global
        {}
    )

    imprimir_ocupacion_turnos_dia(dia.get("ocupacion_recursos", {}), cfg_dia)

    

if __name__ == "__main__":
    test_ciclo_completo()
