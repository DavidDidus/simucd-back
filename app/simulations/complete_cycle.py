# app/simulations/complete_cycle.py
import sys
import os

# Agregar el directorio raíz al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

# Importaciones
from app.simulations.night.simulation import simular_turno_prioridad_rng
from app.simulations.night.config import DEFAULT_CONFIG as NIGHT_CONFIG
from app.simulations.day.simulation import simular_turno_dia_desde_noche

def simular_ciclo_completo_24h(total_cajas_facturadas, cajas_para_pick, seed=None):
    """
    Simula un ciclo completo de 24 horas: noche + día
    """
    print("🌙 INICIANDO SIMULACIÓN TURNO NOCTURNO")
    print("="*50)
    
    # 1. Simular turno de la noche
    resultado_noche = simular_turno_prioridad_rng(
        total_cajas_facturadas=total_cajas_facturadas,
        cajas_para_pick=cajas_para_pick,
        cfg=NIGHT_CONFIG,
        seed=seed
    )
    
    print(f"\n✅ Turno nocturno completado:")
    print(f"   - Camiones únicos: {len(resultado_noche['info_reutilizacion']['camiones_v1'])}")
    print(f"   - Pallets listos para día: {len(resultado_noche['estado_inicial_dia']['pallets_listos_para_carga'])}")
    
    print("\n☀️  INICIANDO SIMULACIÓN TURNO DIURNO")
    print("="*50)
    
    # 2. Simular turno del día usando el módulo day
    resultado_dia = simular_turno_dia_desde_noche(
        resultado_noche=resultado_noche,
        night_config=NIGHT_CONFIG,
        seed=seed
    )
    
    print(f"\n✅ Turno diurno completado:")
    print(f"   - Camiones que regresaron: {resultado_dia['camiones_procesados']}")
    print(f"   - Vueltas cargadas durante día: {resultado_dia['vueltas_cargadas']}")
    print(f"   - Camiones que salieron en día: {len(resultado_dia['nueva_salida_camiones'])}")
    
    # 3. Mostrar cronograma del día
    mostrar_cronograma_dia(resultado_dia['cronograma_formateado'])
    
    # 4. Consolidar resultados del ciclo completo
    resultado_completo = {
        "ciclo_24h": True,
        "turno_noche": resultado_noche,
        "turno_dia": resultado_dia,
        "resumen_ciclo": {
            "cajas_totales_procesadas": total_cajas_facturadas,
            "vueltas_noche": resultado_noche['vueltas'],
            "camiones_unicos_usados": len(resultado_noche['info_reutilizacion']['camiones_v1']),
            "eficiencia_reutilizacion": resultado_noche['info_reutilizacion']['estadisticas']['tasa_reutilizacion'],
            "tiempo_total_operacion": "24 horas (noche + día)",
            "pallets_procesados_noche": resultado_noche['pallets_pre_total'],
            "continuidad_dia": len(resultado_dia['nueva_salida_camiones']) > 0
        }
    }
    
    return resultado_completo

def mostrar_cronograma_dia(cronograma_formateado):
    """
    Muestra el cronograma del día de forma legible
    """
    print(f"\n📅 CRONOGRAMA DEL DÍA:")
    print(f"{'─'*70}")
    print(f"{'Inicio':<8} {'Fin':<8} {'Camión':<8} {'Pallets':<8} {'Cajas':<8} {'Duración':<8}")
    print(f"{'─'*70}")
    
    for evento in cronograma_formateado:
        print(f"{evento['hora_inicio']:<8} {evento['hora_fin']:<8} {evento['camion']:<8} "
              f"{evento['pallets']:<8} {evento['cajas']:<8} {evento['duracion_min']:.1f} min")