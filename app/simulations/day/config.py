DAY_CONFIG = {
    # --- Recursos (día)
    "cap_chequeador": 2,
    "cap_gruero": 4,
    "cap_parrillero": 1,
    "cap_movilizador": 2,
    "cap_patio": 2,

    # --- Turno (min desde el día 0)
    "shift_start_min": 480,      # 08:00
    "shift_end_min": 960,        # +8h -> 16:00 (ajústalo si tu turno es otro)

    # --- Tiempos de operación
    "tiempo_carga_dia_min": (1.0, 4.0),  # grúa por pallet
    "t_ajuste_capacidad": (1.5, 3.0),    # parrillero
    "t_mover_camion": (1.3, 1.4),        # movilizador

    "retorno_weibull": {
            "alpha": 2.1967,   # también aceptamos "alfa" en utils por si lo prefieres
            "beta": 343.6,
            "gamma": 30.126,
        },
        
    # --- Otros
    "debug": True,
}
def get_day_config():
    return DAY_CONFIG.copy()