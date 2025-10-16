# app/simulations/night_shift/config.py

# Configuración exacta de tu simulación
DEFAULT_CONFIG = {
    "camiones": 23,
    "cap_patio": 16,

    # Tamaños de pallet (cajas) por tipo
    "cajas_mixto": (1, 50),
    "cajas_completo": (40, 90),

    # Plan vs carga real
    "target_pallets_por_vuelta": (12,18), 
    "capacidad_pallets_camion": (10,16),  

    # Calidad (chequeo solo en 1ª vuelta)
    "p_defecto": 0.01,

    # Tiempos (min)
    "t_acomodo_primera": (0.4, 0.8),  
    "t_acomodo_otra": (0.4, 0.8),     
    "t_correccion": (1.0, 2.0),       #
    "t_ajuste_capacidad": (1.5, 3.0), #
    "t_mover_camion": (1.0, 2.0),     #

    # Recursos
    "cap_picker": 14,
    "cap_gruero": 4,
    "cap_chequeador": 2,
    "cap_parrillero": 1,
    "cap_movilizador": 1,

    # Turno
    "shift_start_min": 0,            # 00:00
    "shift_end_min": 480,            # 08:00

    # ICE (horas efectivas por picker en el turno)
    "horas_efectivas_ice": 7.1,
}

WEIBULL_CAJAS_PARAMS = {
    "alpha": 4.9329,    # parámetro de forma
    "beta": 808.69,     # parámetro de escala  
    "gamma": 124.63     # parámetro de ubicación (desplazamiento)
}

LOGNORMAL_PALLETS_CHEQUEO = {
    "sigma": 0.54326,
    "mu": -0.5677,
    "gamma": 0.17475
}

CHISQUARED_PREP_MIXTO = {
    "df": 5,          # grados de libertad
    "scale": 0.83594      # escala
}

LOGNORMAL_CARGA_PALLET = {
    "sigma": 0.16484,
    "mu": 0.99524,
    "gamma": -0.95211
}

LOGNORMAL_DESPACHO_COMPLETO = {
    "sigma": 0.51271,
    "mu": 0.50798,
    "gamma": 0.0  # Sin desplazamiento (ajustar si es necesario)
}



# Prioridades para la grúa (menor número = mayor prioridad)
PRIO_R1 = 0       # vuelta 1 (carga/chequeo/acomodo/despacho completo)
PRIO_R2PLUS = 1   # vueltas >=2 (staging)
