# app/simulations/night_shift/dists.py
import math
import numpy as np
from .config import (
    LOGNORMAL_PALLETS_CHEQUEO, LOGNORMAL_CARGA_PALLET,
    LOGNORMAL_DESPACHO_COMPLETO
)

def _as_np_rng(rng):
    # Garantiza un np.random.Generator sin romper la semilla que venga
    if hasattr(rng, "lognormal"):
        return rng
    # fallback: crear uno nuevo
    return np.random.default_rng()

def sample_pallets_chequeados_por_minuto(rng):
    np_rng = _as_np_rng(rng)
    muestra = np_rng.lognormal(
        mean=LOGNORMAL_PALLETS_CHEQUEO["mu"],
        sigma=LOGNORMAL_PALLETS_CHEQUEO["sigma"]
    )
    return max(0.1, min(muestra + LOGNORMAL_PALLETS_CHEQUEO["gamma"], 1.85))

def sample_tiempo_chequeo_unitario(rng, mean=1.0, cv=0.30, low=0.4, high=2.0, max_resamples=8):
    """
    Tiempo por pallet (min). Lognormal truncada con media≈mean y CV≈cv.
    Truncamos a [low, high] para evitar colas irreales y recalibrar el cuello.
    """
    # parámetros lognormales desde mean y cv:
    # sigma = sqrt(ln(1+cv^2)), mu = ln(mean) - 0.5*sigma^2
    sigma = math.sqrt(math.log(1.0 + cv*cv))
    mu = math.log(mean) - 0.5 * sigma * sigma

    # muestreo con truncación por rechazo (rápido dado el rango estrecho)
    for _ in range(max_resamples):
        x = rng.lognormal(mean=mu, sigma=sigma)
        if low <= x <= high:
            return x
    # fallback si no cayó en rango en pocos intentos
    return min(max(x, low), high)

def sample_tiempo_carga_pallet(rng):
    np_rng = _as_np_rng(rng)
    muestra = np_rng.lognormal(
        mean=LOGNORMAL_CARGA_PALLET["mu"],
        sigma=LOGNORMAL_CARGA_PALLET["sigma"]
    )
    return max(0.1, min(muestra + LOGNORMAL_CARGA_PALLET["gamma"], 2.5))

def sample_tiempo_despacho_completo(rng):
    np_rng = _as_np_rng(rng)
    muestra = np_rng.lognormal(
        mean=LOGNORMAL_DESPACHO_COMPLETO["mu"],
        sigma=LOGNORMAL_DESPACHO_COMPLETO["sigma"]
    )
    return max(0.2, min(muestra + LOGNORMAL_DESPACHO_COMPLETO.get("gamma", 0.0), 2.5))

def sample_dagum_cajas(rng):
   
    """
    Genera muestras de una distribución Dagum.
    a = parámetro de forma 1
    p = parámetro de forma 2
    b = parámetro de escala
    """
    a=11.436
    p=0.17161 
    b=792.92

    u = np.random.uniform(0, 1)
    return b * ((u ** (-1/p)) - 1) ** (-1/a)

def sample_weibull_cajas(rng, alpha, beta, gamma):
    u = rng.random()
    u = max(u, 1e-10)
    valor = beta * ((-math.log(u)) ** (1.0 / alpha)) + gamma
    return max(1, int(round(valor)))

def sample_chisquared_prep_mixto(rng, df, gamma):
    chi = rng.chisquare(df)
    t = chi + gamma
    if t < 0.2: t = 0.2
    if t > 20:  t = 20
    return t

from math import exp


def sample_lognormal_retorno_camion(
    rng,
    sigma=0.0232, mu=8.8962, gamma=-6979.4,
    # α calibrado para que, después de winsorizar en p90, la media ≈ 240 min
    alpha=0.7505,
):
    """
    Devuelve el tiempo de retorno (min) con:
      - Truncado a 0,
      - Corte (winsor) en p90 (tope superior como ya estaba),
      - Escala α,
      - Mínimo absoluto de 60 min (1 hora).
    """
    # Z-score para el percentil 90 de una Normal estándar
    _Z90 = 1.2815515655446004

    # p90 de la lognormal desplazada (antes de truncado a 0)
    p90_base = math.exp(mu + sigma * _Z90) + gamma

    # Muestra base
    t = rng.lognormal(mean=mu, sigma=sigma) + gamma
    t = max(0.0, t)           # no negativos

    # Winsor superior en p90 (mantiene tu tope original)
    t = min(t, p90_base)

    # Reescalado para la media objetivo
    t = alpha * t

    # Límite inferior: 60 min (1 hora)
    t = max(60.0, t)

    return t
