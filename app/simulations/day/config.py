# app/simulations/day/config.py
"""
Configuraciones específicas para el turno del día
"""

# Configuración base para el día
DAY_CONFIG = {
    # Tiempos de operación
    "shift_start_min": 480,      # 8:00 AM
    "shift_end_min": 1440,       # 12:00 AM (medianoche)
    
    # Tiempos de carga (más rápidos que la noche)
    "tiempo_carga_dia_min": [1, 4],  # minutos por pallet
    
    # Recursos
    "cap_gruero": 6,             # Más capacidad de grúa durante el día
    
    # Retornos de camiones
    "tiempo_base_retorno_min": 60,    # 1 hora después del inicio (9:00 AM)
    "intervalo_retorno_min": 30,      # 30 minutos entre retornos
    
    # Distribuciones de tiempo (para futuras mejoras)
    "distribucion_retorno": "uniforme",  # uniforme, normal, exponencial
    "variabilidad_retorno_min": 15,      # ±15 min de variabilidad
}

# Configuración combinada (hereda de night + día)
def get_day_config(night_config):
    """
    Combina configuración de la noche con configuración específica del día
    """
    combined_config = {**night_config, **DAY_CONFIG}
    return combined_config