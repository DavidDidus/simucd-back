# app/simulations/night_shift/utils.py
import random

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