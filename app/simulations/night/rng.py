# app/simulations/night_shift/rng.py
import numpy as np

def make_rng(seed=None):
    """Crea un RNG local. seed=None => diferente cada corrida."""
    return np.random.default_rng(seed)

def U_rng(rng, a, b):
    return rng.uniform(a, b)

def RI_rng(rng, a, b):
    return rng.integers(int(a), int(b) + 1)

def sample_int_or_range_rng(rng, val):
    """Si val es (a, b) -> randint(a, b); si es int -> val."""
    if isinstance(val, (tuple, list)) and len(val) == 2:
        return RI_rng(rng, val[0], val[1])
    return int(val)
