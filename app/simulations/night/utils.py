# app/simulations/night_shift/utils.py

def hhmm_dias(mins: float) -> str:
    """Convierte minutos relativos a 'D# HH:MM' (D0 si es el mismo día)."""
    m = int(round(mins))
    d, rem = divmod(m, 1440)
    h, mm = divmod(rem, 60)
    return (f"D{d} {h:02d}:{mm:02d}" if d > 0 else f"{h:02d}:{mm:02d}")
