from .night.config import DEFAULT_CONFIG as DEFAULT_NIGHT_CFG
from .night.simulation import simular_turno_prioridad_rng
from .day.simulation import simular_turno_dia
from .day.config import get_day_config

def simular_ciclo_completo_24h(total_cajas_facturadas, cajas_para_pick, seed=None,
                               cfg_noche=None):
    """
    Ejecuta: Turno NOCHE -> genera estado -> Turno DÍA (2ª vuelta), y retorna ambos resultados.
    """
    # --- Turno Noche
    night_cfg = dict(DEFAULT_NIGHT_CFG)
    if cfg_noche:
        night_cfg.update(cfg_noche)

    turno_noche = simular_turno_prioridad_rng(
        total_cajas_facturadas=total_cajas_facturadas,
        cajas_para_pick=cajas_para_pick,
        cfg=night_cfg,
        seed=seed,
    )

    # --- Turno Día (a partir del estado de noche)
    estado_inicial = turno_noche.get("estado_inicial_dia", {})  # generado por reporting del turno noche
    day_cfg = get_day_config()
   

    turno_dia = simular_turno_dia(estado_inicial, seed=seed)

    return {
        "turno_noche": turno_noche,
        "turno_dia": turno_dia,
        "cfg_noche": night_cfg,
        "cfg_dia": day_cfg,
    }
