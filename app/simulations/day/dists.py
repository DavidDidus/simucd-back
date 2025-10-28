# app/simulations/day/dists.py
import math
from ..night.dists import (
    sample_tiempo_chequeo_unitario,   # <— re-export de noche
    sample_tiempo_carga_pallet,       # <— re-export de noche
)

"""
Hito 0 – Portería ...
(… tu docstring original …)
"""

# ------------------- EXISTENTE: retorno de camión (no tocar) -------------------
def sample_lognormal_retorno_camion(
    rng,
    sigma=0.0232, mu=8.8962, gamma=-6979.4,
    alpha=0.7505,
):
    _Z90 = 1.2815515655446004
    p90_base = math.exp(mu + sigma * _Z90) + gamma
    t = rng.lognormal(mean=mu, sigma=sigma) + gamma
    t = max(0.0, t)
    t = min(t, p90_base)
    t = alpha * t
    t = max(60.0, t)
    return t

# ------------------- Helpers de muestreo con desplazamiento -------------------
def _u01_safe(rng):
    u = float(rng.random())
    if u <= 1e-12: u = 1e-12
    elif u >= 1.0 - 1e-12: u = 1.0 - 1e-12
    return u

def _sample_weibull_shifted(rng, alpha: float, beta: float, gamma: float) -> float:
    u = _u01_safe(rng)
    w = beta * (-math.log(1.0 - u)) ** (1.0 / alpha)
    return max(0.0, gamma + w)

def _sample_loglogistic_shifted(rng, alpha: float, beta: float, gamma: float) -> float:
    u = _u01_safe(rng)
    t = beta * (u / (1.0 - u)) ** (1.0 / alpha)
    return max(0.0, gamma + t)

def _sample_lognormal_shifted(rng, mu: float, sigma: float, gamma: float) -> float:
    t = rng.lognormal(mean=mu, sigma=sigma) + gamma
    return max(0.0, float(t))

# ------------------- Deltas entre hitos (minutos) -----------------------------
def sample_delta_hito0_1(rng):
    """Weibull α=0.59478, β=13.355, γ=1.1574e-5."""
    return _sample_weibull_shifted(rng, alpha=0.59478, beta=13.355, gamma=1.1574e-5)

def sample_delta_hito1_2(rng):
    """Lognormal σ=0.24631, μ=4.9548, γ=−84.283."""
    return _sample_lognormal_shifted(rng, mu=4.9548, sigma=0.24631, gamma=-84.283)

def sample_delta_hito2_3(rng):
    """Lognormal σ=1.4692, μ=1.2676, γ=−0.00426."""
    return _sample_lognormal_shifted(rng, mu=1.2676, sigma=1.4692, gamma=-0.00426)

__all__ = [
    "sample_tiempo_chequeo_unitario",
    "sample_tiempo_carga_pallet",
    "sample_lognormal_retorno_camion",
    "sample_delta_hito0_1", "sample_delta_hito1_2", "sample_delta_hito2_3",
]
