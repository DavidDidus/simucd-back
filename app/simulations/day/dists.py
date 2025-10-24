import numpy as np
import math

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
