from typing import Dict, List, Tuple, Any
from ..night.metrics import calcular_ocupacion_recursos as _calc  # cálculo nocturno (se usa como base)
import math

# ----------------------------
# Mapeos de nombres de recurso
# ----------------------------

# Nombre de sección en el reporte -> (alias singular, clave de capacidad base en cfg)
RES_NAME_TO_CFG = {
    "grueros":      ("grua",        "cap_gruero"),
    "chequeadores": ("chequeador",  "cap_chequeador"),
    "parrilleros":  ("parrillero",  "cap_parrillero"),
    "movilizadores":("movilizador", "cap_movilizador"),
    "porteros":     ("porteria",    "cap_porteria"),
    "pickers":      ("pickers",     "cap_pickers"),
}

# Clave que viene en 'caps' (override por turno) -> nombre de sección del reporte
SHIFT_CAPS_KEY_TO_REPNAME = {
    "grua":         "grueros",
    "chequeador":   "chequeadores",
    "parrillero":   "parrilleros",
    "movilizador":  "movilizadores",
    "porteria":     "porteros",
    "pickers":      "pickers",
}

# ----------------------------------------------------------------
# Helpers para turnos y línea de tiempo de capacidades (día)
# ----------------------------------------------------------------

def _parse_hhmm_to_min(val: Any) -> int:
    """Convierte 'HH:MM' a minutos absolutos desde 00:00. Si ya es int/float, lo retorna como int."""
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        s = val.strip()
        if ":" in s:
            hh, mm = s.split(":")
            return int(hh) * 60 + int(mm)
        # Si viene '24' o '24:00' sin ':'
        if s.isdigit():
            v = int(s)
            return v * 60 if v <= 24 else v
    raise ValueError(f"No puedo parsear hora/minutos desde: {val!r}")

def _build_shift_windows(cfg: Dict[str, Any]) -> List[Tuple[int, int, Dict[str, Any]]]:
    """
    Devuelve ventanas de turno de *día* en minutos *relativos al inicio del día de trabajo*.
    Cada item: (start_rel, end_rel, raw_caps)

    - Usa cfg['shift_start_min'] como base (minutos absolutos desde medianoche).
    - 'start' y 'end' en cfg['shifts_day'] pueden venir como 'HH:MM' absolutos o minutos absolutos;
      se convierten a *relativos* restando shift_start_min.
    """
    base_abs = int(cfg.get("shift_start_min", 0))
    end_abs  = int(cfg.get("shift_end_min", base_abs + 8 * 60))
    dur = max(0, end_abs - base_abs)

    raw = cfg.get("shifts_day") or []
    windows: List[Tuple[int, int, Dict[str, Any]]] = []
    for w in raw:
        s_abs = _parse_hhmm_to_min(w.get("start"))
        e_abs = _parse_hhmm_to_min(w.get("end"))
        s_rel = s_abs - base_abs
        e_rel = e_abs - base_abs
        # recorta a [0, dur]
        s_rel = max(0, min(s_rel, dur))
        e_rel = max(0, min(e_rel, dur))
        if e_rel > s_rel:
            windows.append((int(s_rel), int(e_rel), dict(w.get("caps") or {})))

    # si no hay nada definido, usamos todo el día como una ventana "vacía"
    if not windows:
        windows = [(0, dur, {})]

    # ordenar por inicio
    windows.sort(key=lambda t: (t[0], t[1]))
    return windows

def _capacity_timeline(cfg: Dict[str, Any]) -> List[Tuple[int, int, Dict[str, int]]]:
    """
    Construye una línea de tiempo por tramos [(s,e,caps_dict), ...] para el *día*,
    con capacidades por recurso (en nombres de reporte: 'grueros', 'chequeadores', ...).

    - Cubre todo el intervalo [0, dur) donde dur = shift_end_min - shift_start_min.
    - Parte de capacidades base cfg['cap_*'] y aplica overrides de cfg['shifts_day'].
    - Si hay ventanas superpuestas, la última en la lista tiene precedencia en ese tramo.
    """
    base_abs = int(cfg.get("shift_start_min", 0))
    end_abs  = int(cfg.get("shift_end_min", base_abs + 8 * 60))
    dur = max(0, end_abs - base_abs)

    # capacidades base por nombre de reporte
    base_caps: Dict[str, int] = {}
    for rep_name, (_sing, cap_key) in RES_NAME_TO_CFG.items():
        base_caps[rep_name] = int(cfg.get(cap_key, 0) or 0)

    windows = _build_shift_windows(cfg)  # relativos a 0
    # breakpoints
    bps = {0, dur}
    for s, e, _ in windows:
        bps.add(int(s)); bps.add(int(e))
    bp_sorted = sorted(bps)

    segments: List[Tuple[int, int, Dict[str, int]]] = []
    for i in range(len(bp_sorted) - 1):
        s, e = bp_sorted[i], bp_sorted[i + 1]
        if e <= s:
            continue
        caps = dict(base_caps)
        # aplica overrides activos en [s,e)
        for ws, we, raw in windows:
            if we <= s or ws >= e:
                continue  # sin intersección
            for raw_key, raw_val in (raw or {}).items():
                rep = SHIFT_CAPS_KEY_TO_REPNAME.get(raw_key)
                if not rep:
                    continue
                caps[rep] = int(raw_val)
        segments.append((s, e, caps))
    return segments

def _ops_from_centro(centro: Any) -> Dict[str, List[Tuple[float, float]]]:
    """
    Lee de 'centro' las trazas de operaciones por recurso y devuelve
    {rep_name: [(start, end), ...]} en minutos relativos al inicio del día.

    Soporta:
    - listas de dicts con claves 'start'/'end'
    - listas de tuplas (start, end)
    Fallback: si no hay trazas, quedará lista vacía (se usará prorrateo).
    """
    mapping = {
        "grueros":      "grua_ops",
        "chequeadores": "cheq_ops",
        "parrilleros":  "parr_ops",
        "movilizadores":"movi_ops",
        "porteros":     "port_ops",
        "pickers":      "pick_ops",
    }
    out: Dict[str, List[Tuple[float, float]]] = {k: [] for k in mapping.keys()}

    for rep_name, attr in mapping.items():
        ops = getattr(centro, attr, None) or []
        buf: List[Tuple[float, float]] = []
        for item in ops:
            if isinstance(item, dict):
                st = float(item.get("start", 0.0))
                en = float(item.get("end",   st))
                if en > st:
                    buf.append((st, en))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                st = float(item[0]); en = float(item[1])
                if en > st:
                    buf.append((st, en))
        if buf:
            # asegura orden por inicio
            buf.sort(key=lambda p: (p[0], p[1]))
        out[rep_name] = buf
    return out

def _sum_active_in_window(op_intervals: List[Tuple[float, float]],
                          window: Tuple[float, float]) -> float:
    """
    Suma la intersección de los intervalos de operación con la ventana [ws, we).
    """
    ws, we = window
    if we <= ws or not op_intervals:
        return 0.0
    total = 0.0
    for s, e in op_intervals:
        if e <= ws or s >= we:
            continue
        total += max(0.0, min(e, we) - max(s, ws))
    return total

# ----------------------------------------------------------------
# Cálculo final de ocupación del día con detalle por 2 turnos de día
# ----------------------------------------------------------------

def calcular_ocupacion_recursos(centro, cfg: Dict[str, Any], tiempo_total_turno: float) -> Dict[str, Any]:
    """
    Ocupación precisa = (tiempo_activo) / ∫cap(t)·dt, integrando la capacidad en el tiempo
    y generando además el desglose para los 2 turnos de día definidos en cfg['shifts_day'].

    Devuelve un dict por recurso con:
      - 'porcentaje_ocupacion'   : total del día (0–100)
      - 'tiempo_activo'          : minutos totales activos
      - 'operaciones'            : total operaciones
      - 'cap_x_tiempo'           : ∫cap(t)·dt del día
      - 'por_turno_dia'          : lista con hasta 2 dicts {inicio_min, fin_min, porcentaje_ocupacion, tiempo_activo, cap_x_tiempo}
    """
    # 1) toma estructura base (noche) para mantener compatibilidad
    base = _calc(centro, cfg, tiempo_total_turno)  # puede traer ocupación=0.0 si la noche no midió
    segments = _capacity_timeline(cfg)             # [(s,e,{caps...}), ...]
    windows  = _build_shift_windows(cfg)           # [(s,e,raw), ...]
    two = windows[:2] if len(windows) >= 2 else (windows or [(0, tiempo_total_turno, {})])
    ops_by_res = _ops_from_centro(centro)

    # Inyecta métricas del día y recalcula % con integración de capacidad
    mr = getattr(centro, "metricas_recursos", {}) or {}
    for rep_name, v in mr.items():
        b = base.setdefault(rep_name, {})
        op_intervals = ops_by_res.get(rep_name, [])
        # Numerador: tiempo activo real (si hay trazas) o el contador existente
        activo_total = (
            sum((end - start) for start, end in op_intervals)
            if op_intervals else
            float(v.get("tiempo_activo", 0) or 0.0)
        )
        # Denominador (día completo): ∫ cap(t) dt
        denom_total = 0.0
        for s, e, caps in segments:
            cap = int(caps.get(rep_name, 0) or 0)
            if cap > 0 and e > s:
                denom_total += cap * (e - s)

        # Desglose por los 2 turnos de día
        por_turno = []
        for (ws, we, _raw) in two:
            if op_intervals:
                activo_w = _sum_active_in_window(op_intervals, (ws, we))
            else:
                # prorrateo si no hay trazas (fallback)
                frac = (we - ws) / float(max(1.0, tiempo_total_turno))
                activo_w = activo_total * frac

            denom_w = 0.0
            for s, e, caps in segments:
                if e <= ws or s >= we:
                    continue
                cap = int(caps.get(rep_name, 0) or 0)
                if cap <= 0:
                    continue
                overlap = max(0.0, min(e, we) - max(s, ws))
                denom_w += cap * overlap

            pct_w = 100.0 * min(1.0, activo_w / denom_w) if denom_w > 0 else 0.0
            por_turno.append({
                "inicio_min": int(ws),
                "fin_min": int(we),
                "porcentaje_ocupacion": pct_w,
                "tiempo_activo": activo_w,
                "cap_x_tiempo": denom_w
            })

        # salida consolidada
        b["tiempo_activo"] = activo_total
        b["operaciones"]   = int(v.get("operaciones", 0) or 0)
        b["cap_x_tiempo"]  = denom_total
        b["porcentaje_ocupacion"] = 100.0 * min(1.0, (activo_total / denom_total)) if denom_total > 0 else 0.0
        b["por_turno_dia"] = por_turno

    # Asegura sección 'resumen' presente
    base.setdefault("resumen", base.get("resumen", {}))
    return base
