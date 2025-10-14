# app/simulations/night_shift/utils.py
import random
import numpy as np
import math
from scipy.stats import weibull_min
from .config import LOGNORMAL_PALLETS_CHEQUEO

LOGNORMAL_PALLETS_CHEQUEO = {
    "sigma": 0.54326,
    "mu": -0.5677,
    "gamma": 0.17475
}

def sample_pallets_chequeados_por_minuto(rng):
    """
    Muestrea de la distribución lognormal para pallets chequeados por minuto
    CADA LLAMADA GENERA UNA NUEVA MUESTRA INDEPENDIENTE
    """
    # Asegurar que tenemos un generador numpy
    if hasattr(rng, 'lognormal'):
        np_rng = rng
    else:
        # Convertir usando estado actual (no semilla fija)
        state = rng.getstate()
        np_rng = np.random.default_rng()
        # Avanzar el generador usando el estado actual
        for _ in range(state[1][0] % 1000):
            np_rng.random()
    
    # *** GENERAR NUEVA MUESTRA LOGNORMAL INDEPENDIENTE ***
    muestra = np_rng.lognormal(
        mean=LOGNORMAL_PALLETS_CHEQUEO["mu"],
        sigma=LOGNORMAL_PALLETS_CHEQUEO["sigma"]
    )
    
    # Aplicar desplazamiento gamma
    resultado = muestra + LOGNORMAL_PALLETS_CHEQUEO["gamma"]
    
    # Asegurar que sea positivo y razonable
    return max(0.1, min(resultado, 10.0))

def calcular_tiempo_chequeo_lognormal(num_pallets, rng):
    """
    Calcula tiempo de chequeo basado en UNA NUEVA muestra lognormal
    """
    if num_pallets <= 0:
        return 0, 0
    
    # *** OBTENER NUEVA TASA PARA CADA LLAMADA ***
    pallets_por_minuto = sample_pallets_chequeados_por_minuto(rng)
    
    # Calcular tiempo total
    tiempo_chequeo = num_pallets / pallets_por_minuto
    
    return tiempo_chequeo, pallets_por_minuto


def sample_weibull_cajas(rng, alpha, beta, gamma):
    """
    Genera capacidad de cajas usando distribución Weibull de 3 parámetros.
    
    Args:
        rng: generador de números aleatorios
        alpha: parámetro de forma (shape)
        beta: parámetro de escala (scale) 
        gamma: parámetro de ubicación (location/shift)
    
    Returns:
        int: capacidad de cajas (entero positivo)
    """    
    u = rng.random()  # Uniforme entre 0 y 1
    u = max(u, 1e-10)
    
    # Transformación inversa de Weibull
    valor = beta * ((-math.log(u)) ** (1.0 / alpha)) + gamma
    
    # Asegurar que sea entero positivo
    cajas = max(1, int(round(valor)))
    
    return cajas

def calcular_capacidad_objetiva(total_cajas_facturadas, num_camiones_estimado):
    """
    Calcula una capacidad de cajas objetiva basada en la carga total.
    """
    # Agregar 20% de margen para eficiencia
    capacidad_promedio_objetiva = (total_cajas_facturadas / num_camiones_estimado) * 1.2
    return max(800, int(capacidad_promedio_objetiva))  # Mínimo 800 cajas


def make_rng(seed=None):
    """Crea un RNG local. seed=None => diferente cada corrida."""
    return random.Random(seed)

def U_rng(rng, a, b):
    return rng.uniform(a, b)

def RI_rng(rng, a, b):
    return rng.randint(int(a), int(b))

def sample_int_or_range_rng(rng, val):
    """Si val es (a,b)-> randint(a,b); si es int -> ese int."""
    if isinstance(val, (tuple, list)) and len(val) == 2:
        return RI_rng(rng, val[0], val[1])
    return int(val)

def hhmm_dias(mins: float) -> str:
    m = int(round(mins))
    d, rem = divmod(m, 1440)
    h, mm = divmod(rem, 60)
    return (f"D{d} {h:02d}:{mm:02d}" if d>0 else f"{h:02d}:{mm:02d}")
