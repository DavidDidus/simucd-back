# app/simulations/night_shift/__init__.py
from .simulation import simular_turno_prioridad_rng
from .config import DEFAULT_CONFIG

__all__ = ['simular_turno_prioridad_rng', 'DEFAULT_CONFIG']

# En tu endpoint de FastAPI
#from app.simulations.night_shift import simular_turno_prioridad_rng, DEFAULT_CONFIG

# Ejecutar simulación
#result = simular_turno_prioridad_rng(
#    total_cajas=35000,
#    cfg=DEFAULT_CONFIG,
#    seed=123
#)