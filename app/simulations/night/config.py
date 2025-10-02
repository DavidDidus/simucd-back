# app/simulations/night_shift/config.py

# Configuración exacta de tu simulación
DEFAULT_CONFIG = {
    "camiones": 21,
    "cap_patio": 16,                 # SOLO restringe camiones de la 1ª vuelta (carga)

    # Tamaños de pallet (cajas) por tipo
    "cajas_mixto": (1, 40),
    "cajas_completo": (40, 70),

    # Plan vs carga real
    "target_pallets_por_vuelta": (15,22), # asignación PRE-fusión por camión (rango)
    "capacidad_pallets_camion": (10,16),  # capacidad real por camión en 1ª vuelta (post-fusión, solo mixtos)

    # Calidad (chequeo solo en 1ª vuelta)
    "p_defecto": 0.02,

    # Tiempos (min)
    "t_prep_mixto": (6,10),
    "t_desp_completo": (1,2.5),

    "t_acomodo_primera": (0.5,1.5),  # 1er pallet del camión
    "t_acomodo_otra": (0.5,1,5),         # siguientes pallets

    # SOLO 1ª vuelta:
    "t_chequeo_pallet": (1,3),
    "t_correccion": (2,3),
    "t_carga_pallet": (1.0,2.0),
    "t_ajuste_capacidad": (3,5),
    "t_mover_camion": (2,4),

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

    "batch_acomodo": True,           # Agrupar operaciones de acomodo
    "prefetch_completos": True,      # Pre-posicionar pallets completos

}

# Prioridades para la grúa (menor número = mayor prioridad)
PRIO_R1 = 0       # vuelta 1 (carga/chequeo/acomodo/despacho completo)
PRIO_R2PLUS = 1   # vueltas >=2 (staging)
