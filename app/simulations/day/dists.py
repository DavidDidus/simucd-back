# app/simulations/day/dists.py
import math

"""
Hito 0 – Portería (Weibull α=0.7133, β=17.514, γ=0.01667): 21.80 min (≈ 0h 22m)

Hito 1 – Entrada a planta (Log-logistic α=5.1909, β=110.27, γ=−29.863): 87.44 min (≈ 1h 27m)

Hito 2 – Chequeo+Descarga+Carga (Lognormal σ=1.5449, μ=1.3345, γ=0): 12.53 min (≈ 0h 13m)

Nota: en el código, H2 completo está puesto en descarga_carga; chequeo_inicial vale 0.0 para no duplicar.

Hito 3 – Chequeo de salida (Log-logistic α=3.7941, β=10.072, γ=−1.006): 10.32 min (≈ 0h 10m)
"""


# ------------------- EXISTENTE: retorno de camión (no tocar) -------------------
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
    """Uniforme(0,1) segura para inversas (evita extremos 0 y 1)."""
    u = float(rng.random())
    if u <= 1e-12:
        u = 1e-12
    elif u >= 1.0 - 1e-12:
        u = 1.0 - 1e-12
    return u

def _sample_weibull_shifted(rng, alpha: float, beta: float, gamma: float) -> float:
    """Weibull desplazada: T = gamma + Weibull(alpha, beta). (minutos)"""
    u = _u01_safe(rng)
    w = beta * (-math.log(1.0 - u)) ** (1.0 / alpha)
    return max(0.0, gamma + w)

def _sample_loglogistic_shifted(rng, alpha: float, beta: float, gamma: float) -> float:
    """
    Log-logistic (F(t)=1/(1+(beta/t)^alpha), t>0) con desplazamiento gamma.
    Inversa: t = beta * (u/(1-u))^(1/alpha)
    """
    u = _u01_safe(rng)
    t = beta * (u / (1.0 - u)) ** (1.0 / alpha)
    return max(0.0, gamma + t)

def _sample_lognormal_shifted(rng, mu: float, sigma: float, gamma: float) -> float:
    """Lognormal con desplazamiento gamma (minutos)."""
    t = rng.lognormal(mean=mu, sigma=sigma) + gamma
    return max(0.0, float(t))


# ------------------- Deltas entre hitos (minutos) ---------------------
# Tiempos entre hitos para T1: 0→1, 1→2, 2→3.

def sample_delta_hito0_1(rng):
    """Delta H0→H1: Weibull desplazada (alpha=0.59478, beta=13.355, gamma=1.1574e-5)."""
    return _sample_weibull_shifted(rng, alpha=0.59478, beta=13.355, gamma=1.1574e-5)

def sample_delta_hito1_2(rng):
    """Delta H1→H2: Lognormal desplazada (sigma=0.24631, mu=4.9548, gamma=-84.283)."""
    return _sample_lognormal_shifted(rng, mu=4.9548, sigma=0.24631, gamma=-84.283)

def sample_delta_hito2_3(rng):
    """Delta H2→H3: Lognormal desplazada (sigma=1.4692, mu=1.2676, gamma=-0.00426)."""
    return _sample_lognormal_shifted(rng, mu=1.2676, sigma=1.4692, gamma=-0.00426)
