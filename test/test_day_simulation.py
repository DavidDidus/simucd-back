# test_complete_cycle.py
import sys
import os

# Agregar el directorio app al path si no está
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.simulations.complete_cycle import simular_ciclo_completo_24h

def test_ciclo_completo():
    resultado = simular_ciclo_completo_24h(
        total_cajas_facturadas=30000,
        cajas_para_pick=28000,
        seed=42
    )
    
    # Analizar continuidad noche-día
    noche = resultado["turno_noche"]
    dia = resultado["turno_dia"]
    
    print("\n📊 ANÁLISIS DE CONTINUIDAD:")
    print(f"Camiones V1 noche: {noche['info_reutilizacion']['camiones_v1']}")
    print(f"Camiones que regresaron día: {[c['camion_id'] for c in dia['nueva_salida_camiones']]}")
    
    # Verificar que los mismos camiones aparecen en ambos turnos
    camiones_noche = set(noche['info_reutilizacion']['camiones_v1'])
    camiones_dia = set(c['camion_id'] for c in dia['nueva_salida_camiones'])
    
    print(f"Continuidad verificada: {camiones_noche.intersection(camiones_dia)}")

if __name__ == "__main__":
    test_ciclo_completo()