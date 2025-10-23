import numpy as np

def sample_lognormal_retorno_camion(rng, sigma=0.0232, mu=8.8962, gamma=-6979.4):
    """
    Tiempo de retorno del camión (min) ~ LogNormal(mu, sigma) + gamma (desplazado).
    Ajusta parámetros según tus datos; gamma puede ser negativo.
    """
    val = rng.lognormal(mean=mu, sigma=sigma)
    return max(0.0, val + gamma)
