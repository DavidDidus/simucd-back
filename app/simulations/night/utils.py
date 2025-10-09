# app/simulations/night_shift/utils.py
import random
import numpy as np
import math
from scipy.stats import weibull_min

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
    # Implementación directa de Weibull usando transformación inversa
    # X = beta * (-ln(U))^(1/alpha) + gamma
    # donde U es uniforme(0,1)
    
    u = rng.random()  # Uniforme entre 0 y 1
    # Evitar log(0)
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
