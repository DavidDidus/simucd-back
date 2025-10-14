# app/simulations/night_shift/utils.py
import random
import numpy as np
import math
from .config import LOGNORMAL_PALLETS_CHEQUEO, LOGNORMAL_CARGA_PALLET, LOGNORMAL_DESPACHO_COMPLETO


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
    return max(0.1, min(resultado, 1.85))

def sample_chisquared_prep_mixto(rng, df, gamma):
    """
    Muestrea tiempo de preparación de pallet mixto usando distribución Chi-cuadrado
    
    Args:
        rng: Generador de números aleatorios numpy
        df: Grados de libertad (v)
        gamma: Parámetro de desplazamiento
    
    Returns:
        float: Tiempo de preparación en minutos
    """

    # Generar muestra de chi-cuadrado
    chi_sq_sample = rng.chisquare(df)
    
    # Aplicar desplazamiento
    tiempo_prep = chi_sq_sample + gamma
    
    # Asegurar que el tiempo sea positivo y razonable
    # (opcionalmente puedes agregar límites min/max)
    if tiempo_prep < 0.2:
        tiempo_prep = 0.2  # mínimo 12 segundos
    elif tiempo_prep > 20:
        tiempo_prep = 20   # máximo 20 minutos (outlier)
    
    print(f"   Tiempo prep mixto (Chi-cuadrado): {tiempo_prep:.2f} min")
    return tiempo_prep

def calcular_tiempo_chequeo_lognormal(num_pallets, rng):
    """
    Calcula tiempo de chequeo basado en UNA NUEVA muestra lognormal
    """
    if num_pallets <= 0:
        return 0, 0
    
    # Calcular tiempo individual para cada pallet y sumarlos
    tiempos_pallets = [1.0 / sample_pallets_chequeados_por_minuto(rng) for _ in range(num_pallets)]
    tiempo_chequeo = sum(tiempos_pallets)
    
    # Para referencia, devolver también el último pallets_por_minuto generado
    return tiempo_chequeo, tiempos_pallets[-1] if tiempos_pallets else 0

def sample_tiempo_carga_pallet(rng):
    """
    Muestrea de la distribución lognormal para tiempo de carga de pallet al camión
    CADA LLAMADA GENERA UNA NUEVA MUESTRA INDEPENDIENTE
    
    Returns:
        float: Tiempo de carga en minutos
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
        mean=LOGNORMAL_CARGA_PALLET["mu"],
        sigma=LOGNORMAL_CARGA_PALLET["sigma"]
    )
    
    # Aplicar desplazamiento gamma
    resultado = muestra + LOGNORMAL_CARGA_PALLET["gamma"]
    
    # Asegurar que sea positivo y razonable (0.1 min a 2 min por pallet)
    return max(0.1, min(resultado, 2.5))

def sample_tiempo_despacho_completo(rng):
    """
    🆕 Muestrea de la distribución lognormal para tiempo de despacho de pallet completo
    CADA LLAMADA GENERA UNA NUEVA MUESTRA INDEPENDIENTE
    
    Args:
        rng: np.random.Generator
    
    Returns:
        float: Tiempo de despacho en minutos
    """
    # Generar nueva muestra lognormal independiente
    muestra = rng.lognormal(
        mean=LOGNORMAL_DESPACHO_COMPLETO["mu"],
        sigma=LOGNORMAL_DESPACHO_COMPLETO["sigma"]
    )
    
    # Aplicar desplazamiento gamma (si existe)
    resultado = muestra + LOGNORMAL_DESPACHO_COMPLETO.get("gamma", 0.0)
    
    # Asegurar que sea positivo y razonable (0.2 min a 2 min por pallet)
    # Típicamente el despacho es más rápido que la carga
    return max(0.2, min(resultado, 2.5))

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
    return np.random.default_rng(seed)

def U_rng(rng, a, b):
    return rng.uniform(a, b)

def RI_rng(rng, a, b):
    return rng.integers(int(a), int(b)+1)

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
