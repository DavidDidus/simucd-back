# app/simulations/night_shift/config.py

# Configuración exacta de tu simulación
DEFAULT_CONFIG = {
    "camiones": 23,
    "cap_patio": 16,

    # Tamaños de pallet (cajas) por tipo
    "cajas_mixto": (1, 50),
    "cajas_completo": (40, 90),

    # Plan vs carga real
    "target_pallets_por_vuelta": (12,22), 
    "capacidad_pallets_camion": (10,11),  

    # Calidad (chequeo solo en 1ª vuelta)
    "p_defecto": 0.01,

    # Tiempos (min)
    "t_prep_mixto": (4, 7),            
    "t_desp_completo": (1, 2),          
    "t_acomodo_primera": (0.6, 1.2),  
    "t_acomodo_otra": (0.4, 0.8),     
    "t_chequeo_pallet": (0.4, 1),     
    "t_correccion": (1.0, 2.0),       
    "t_carga_pallet": (0.8, 1.5),     
    "t_ajuste_capacidad": (1.5, 3.0), 
    "t_mover_camion": (1.0, 2.0),     

    # Recursos
    "cap_picker": 14,
    "cap_gruero": 5,                 # grúa única lógica con capacidad 4 (sin roles)
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

# Prioridades para la grúa (menor número = mayor prioridad)
PRIO_R1 = 0       # vuelta 1 (carga/chequeo/acomodo/despacho completo)
PRIO_R2PLUS = 1   # vueltas >=2 (staging)
