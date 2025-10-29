# app/simulations/day/config.py

DAY_CONFIG = {
    "shift_start_min": 480,     # 08:00
    "shift_end_min": 1440,      # 24:00 (00:00)
    # Turnos del día (solo cambia dotación)
    "shifts_day": [{
        "start": "08:00", 
        "end": "16:00",
        "caps": {
            "grua": 4, 
            "chequeador": 2, 
            "parrillero": 1, 
            "movilizador": 1, 
            "porteria": 1
            }
        },
    {
        "start": "16:00", 
        "end": "24:00",
        "caps": {
            "grua": 2, 
            "chequeador": 1, 
            "parrillero": 1, 
            "movilizador": 1, 
            "porteria": 1
        }
    },],
    
    # --- Tiempos de operación (día)
    "tiempo_carga_dia_min": (1.0, 4.0),  # grúa por pallet
    "t_ajuste_capacidad": (1.5, 3.0),    # parrillero
    "t_mover_camion": (1.3, 1.4),        # movilizador

    # --- Distribución de retornos (v>=2) usada actualmente
    "retorno_weibull": {
        "alpha": 2.1967,
        "beta": 343.6,
        "gamma": 30.126,
    },

    # --- NUEVO: Cantidad de llegadas T1 en el día (no interarribos)
    # Usamos tu Weibull tal cual, pero para samplear N de camiones.
    "t1_cantidad_dia_weibull": {
        "alpha": 2.0263,
        "beta": 8.9071,
        "gamma": 0.0,
    },
    "t1_max_por_dia": 30,     # límite superior esperado (ajústalo si quieres)
    "t1_habilitado": True,
    "t1_prefijo_id": "T1",

    # --- Otros
    "debug": True,
}

def get_day_config():
    return DAY_CONFIG.copy()
