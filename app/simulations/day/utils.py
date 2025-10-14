# app/simulations/day/utils.py
"""
Utilidades específicas para la simulación del día
"""
import sys
import os

# Importar utilidades de la noche
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))
from app.simulations.night.utils import make_rng, hhmm_dias, U_rng

def calcular_tiempo_retorno(indice_camion, cfg, rng):
    """
    Calcula el tiempo de retorno de un camión basado en la configuración
    """
    tiempo_base = cfg.get("tiempo_base_retorno_min", 60)
    intervalo = cfg.get("intervalo_retorno_min", 30)
    variabilidad = cfg.get("variabilidad_retorno_min", 15)
    
    # Tiempo base escalonado
    tiempo_escalonado = tiempo_base + (indice_camion * intervalo)
    
    # Agregar variabilidad aleatoria
    variacion = U_rng(rng, -variabilidad, variabilidad)
    tiempo_final = max(0, tiempo_escalonado + variacion)
    
    return tiempo_final

def calcular_tiempo_carga_dia(num_pallets, cfg, rng):
    """
    Calcula el tiempo de carga durante el día
    """
    if num_pallets == 0:
        return 0
    
    tiempo_rango = cfg.get("tiempo_carga_dia_min", [1, 4])
    tiempo_por_pallet = U_rng(rng, tiempo_rango[0], tiempo_rango[1])
    
    return tiempo_por_pallet * num_pallets

def formatear_cronograma_dia(eventos):
    """
    Formatea los eventos del día para mostrar un cronograma legible
    """
    cronograma = []
    for evento in eventos:
        entrada = {
            "hora_inicio": evento["inicio_hhmm"],
            "hora_fin": evento["fin_hhmm"],
            "camion": evento["camion_id"],
            "operacion": evento.get("modo", "carga_dia"),
            "pallets": evento.get("num_pallets", 0),
            "cajas": evento["cajas_pre"],
            "duracion_min": evento["tiempo_min"]
        }
        cronograma.append(entrada)
    
    return sorted(cronograma, key=lambda x: x["hora_inicio"])