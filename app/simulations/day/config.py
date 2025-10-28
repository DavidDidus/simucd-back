# app/simulations/day/config.py

DAY_CONFIG = {
    # --- Recursos (día)
    "cap_chequeador": 2,
    "cap_gruero": 4,
    "cap_parrillero": 1,
    "cap_movilizador": 2,
    "cap_patio": 2,
    "cap_porteria": 1,   # personal de portería para T1 (Hito 0)

    # --- Turno (min desde 00:00)
    "shift_start_min": 480,      # 08:00
    "shift_end_min": 960,        # 16:00

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
