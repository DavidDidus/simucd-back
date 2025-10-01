# -*- coding: utf-8 -*-
import simpy, random
from math import ceil
from collections import defaultdict

# ================= Configuración =================
cfg = {
    "camiones": 21,
    "cap_patio": 16,                 # SOLO restringe camiones de la 1ª vuelta (carga)

    # Entrada: CAJAS -> pallets pre-fusión (muestreo por pallet)
    "sold_mode": "unidades",         # trabajamos en cajas
    "cajas_mixto": (1, 40),
    "cajas_completo": (40, 70),
    "p_mixto": 0.60,                 # prob. de que un pallet pre-fusión sea mixto

    # Plan vs carga real
    "target_pallets_por_vuelta": (15,22), # asignación PRE-fusión por camión (rango)
    "capacidad_pallets_camion": (10,16),  # capacidad real por camión en 1ª vuelta (post-fusión, solo mixtos)

    # Calidad (chequeo solo en 1ª vuelta)
    "p_defecto": 0.02,

    # Tiempos (min)
    
    "t_prep_mixto": (6,10),
    "t_desp_completo": (2,3),

    "t_acomodo_primera": (1.5,2.0),  # 1er pallet del camión
    "t_acomodo_otra": (1,2),         # siguientes pallets

    # SOLO 1ª vuelta:
    "t_chequeo_pallet": (1,3),
    "t_correccion": (2,4),
    "t_carga_pallet": (1.5,2.5),
    "t_ajuste_capacidad": (3,5),
    "t_mover_camion": (2,4),

    # Recursos
    "cap_picker": 14,
    "cap_gruero": 4,                 # <-- 1 sola grúa lógica con capacidad 4 (sin roles)
    "cap_chequeador": 2,
    "cap_parrillero": 1,
    "cap_movilizador": 1,

    # Turno
    "shift_start_min": 0,            # 00:00
    "shift_end_min": 480,            # 08:00
}

# Prioridades para la grúa (menor número = mayor prioridad)
PRIO_R1 = 0       # vuelta 1 (carga/chequeo/acomodo/despacho completo)
PRIO_R2PLUS = 1   # vueltas >=2 (staging)

# ================= RNG local (sin reseed global) =================
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

# ================= Generación de pallets desde CAJAS =================
def generar_pallets_desde_cajas(total_cajas, cfg, rng):
    """
    Devuelve una lista de pallets pre-fusión:
      cada item: {"mixto": bool, "cajas": int}
    Mixtos ~ Uniforme(cfg['cajas_mixto'])
    Completos ~ Uniforme(cfg['cajas_completo'])
    """
    pallets = []
    cajas_rest = total_cajas
    while cajas_rest > 0:
        es_mixto = (rng.random() < cfg["p_mixto"])
        if es_mixto:
            a, b = cfg["cajas_mixto"]
        else:
            a, b = cfg["cajas_completo"]
        cajas = RI_rng(rng, a, b)
        if cajas > cajas_rest:
            cajas = cajas_rest
        pallets.append({"mixto": es_mixto, "cajas": cajas})
        cajas_rest -= cajas
    return pallets  # len(pallets) = pallets pre-fusión

# ================= Planificación por vueltas/camiones =================
def construir_plan_desde_pallets(pallets, cfg, rng):
    """
    Reparte la lista de pallets pre-fusión en vueltas:
    - Por camión: target aleatorio en [15,22] (o el int si fuera fijo).
    - Último camión de la última vuelta puede quedar con menos si no alcanza.
    """
    cam = cfg["camiones"]
    plan = []
    idx = 0
    N = len(pallets)
    vuelta = 0

    while idx < N:
        vuelta += 1
        asignaciones = []
        for _ in range(cam):
            if idx >= N:
                break
            tgt_cam = sample_int_or_range_rng(rng, cfg["target_pallets_por_vuelta"])
            lote = pallets[idx: idx + tgt_cam]
            asignaciones.append(lote)
            idx += len(lote)
        plan.append((vuelta, asignaciones))
    return plan

# ================= Modelo SimPy =================
class Centro:
    def __init__(self, env, cfg, pick_gate, rng):
        self.env = env
        self.cfg = cfg
        self.pick_gate = pick_gate  # {v: {'target':N_cam, 'count':0, 'event':env.event(), 'done_time':None}}
        self.rng = rng

        # Recursos
        self.pick = simpy.Resource(env, capacity=cfg["cap_picker"])
        self.grua = simpy.PriorityResource(env, capacity=cfg["cap_gruero"])  # <-- grúa única con cap=4
        self.cheq = simpy.Resource(env, capacity=cfg["cap_chequeador"])
        self.parr = simpy.Resource(env, capacity=cfg["cap_parrillero"])
        self.movi = simpy.Resource(env, capacity=cfg["cap_movilizador"])
        self.patio_camiones = simpy.Resource(env, capacity=cfg["cap_patio"])  # SOLO 1ª vuelta (carga)

        self.prio_acomodo_v1 = PRIO_R1   # prioridad alta para acomodo en 1ª vuelta
        
        env.process(self._rebalanceo_post_pick_v1()) 

        # Logs
        self.eventos = []          # por camión/vuelta
        self.grua_ops = []         # logs de cada uso de grúa

    def _usar_grua(self, priority, dur, label, vuelta, id_cam):
        """Uso de grúa única (capacidad cfg['cap_gruero']) + log de espera y servicio."""
        t_req = self.env.now
        with self.grua.request(priority=priority) as g:
            yield g
            wait = self.env.now - t_req
            t_start = self.env.now
            yield self.env.timeout(dur)
            t_end = self.env.now
        self.grua_ops.append({
            "vuelta": vuelta, "camion": id_cam, "label": label,
            "wait": wait, "hold": dur, "start": t_start, "end": t_end
        })

    def _rebalanceo_post_pick_v1(self):
        """Cuando termina el pick de la vuelta 1, bajar prioridad de acomodo_v1."""
        # Espera al evento de fin de pick de la vuelta 1
        try:
            ev = self.pick_gate[1]['event']
        except KeyError:
            return  # no hay vuelta 1 (caso raro)
        yield ev
        # Rebalance: sólo acomodo_v1 baja a R2+, carga se mantiene en R1
        self.prio_acomodo_v1 = PRIO_R2PLUS
        print(f"[Rebalance] t={self.env.now:.2f} fin PICK V1 → acomodo_v1 ahora PRIO_R2PLUS")


    def procesa_camion_vuelta(self, vuelta, id_cam, pallets_asignados):
        """
        Gating de pick:
          - Vuelta k+1 comienza PICK cuando vuelta k terminó su PICK.
        Vuelta 1: fusión SOLO mixtos, luego pick + acomodo + chequeo + carga + cierre (parrillero/movilizador).
        Vueltas ≥2: pick + acomodo (staging). Sin chequeo ni carga.
        Las prioridades de grúa dan preferencia a vuelta 1.
        """
        cfg = self.cfg

        # 1) Esperar gate si aplica (vuelta>1 espera fin del PICK de la anterior)
        if vuelta > 1:
            yield self.pick_gate[vuelta - 1]['event']

        # 2) Marca de inicio (después del gate)
        t0 = self.env.now

        # 3) Fusión solo en vuelta 1 y solo sobre pallets mixtos para respetar capacidad del camión
        pre_asignados = pallets_asignados
        post_lista = pre_asignados
        fusionados = 0
        if vuelta == 1:
            cap_cam = sample_int_or_range_rng(self.rng, cfg["capacidad_pallets_camion"])  # 10–16 por camión
            exceso = max(0, len(pre_asignados) - cap_cam)
            if exceso > 0:
                idx_mixtos = [i for i, p in enumerate(pre_asignados) if p["mixto"]]
                a_fusionar = min(exceso, len(idx_mixtos))
                if a_fusionar > 0:
                    quitar = set(self.rng.sample(idx_mixtos, a_fusionar))
                    post_lista = [p for i, p in enumerate(pre_asignados) if i not in quitar]
                    fusionados = a_fusionar
                else:
                    # Si no hay mixtos suficientes para reducir, truncamos a la capacidad (constraint físico).
                    post_lista = pre_asignados[:cap_cam]
                    fusionados = 0

        # 4) FASE A: PICK (por pallet)
        #    - En vuelta 1: se pickean solo los pallets post-fusión
        #    - En vueltas ≥2: se pickean todos los asignados (staging)
        pick_list = post_lista if vuelta == 1 else pre_asignados
        for pal in pick_list:
            with self.pick.request() as r:
                q_pick = len(self.pick.queue); t_req_pick = self.env.now
                yield r
                print(f"[Debug] V{vuelta} C{id_cam}: WAIT pick={self.env.now - t_req_pick:.2f} (cola={q_pick})")
              
                if pal["mixto"]:
                    yield self.env.timeout(U_rng(self.rng, *cfg["t_prep_mixto"]))
                else:
                    pass

            if (not pal["mixto"]) and (vuelta == 1):
                dur = U_rng(self.rng, *cfg["t_desp_completo"])
                yield from self._usar_grua(
                    priority=PRIO_R1,
                    dur=dur,
                    label="pick_completo",   # mantenemos label para tus métricas
                    vuelta=vuelta, id_cam=id_cam
                )

        # 5) Señal de fin de PICK para esta vuelta
        self.pick_gate[vuelta]['count'] += 1
        if self.pick_gate[vuelta]['count'] >= self.pick_gate[vuelta]['target']:
            if not self.pick_gate[vuelta]['event'].triggered:
                self.pick_gate[vuelta]['done_time'] = self.env.now
                self.pick_gate[vuelta]['event'].succeed()

        # 6) FASE B: Post-pick
        corregidos = 0
        primera = True

        if vuelta == 1:

            # 1ª vuelta: ocupar patio y completar acomodo+chequeo+carga por pallet post-fusión
            with self.patio_camiones.request() as slot:
                yield slot

                for pal in post_lista:
                    # Acomodo (grúa alta prioridad)
                    dur_a = U_rng(self.rng, *(cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]))
                    yield from self._usar_grua(self.prio_acomodo_v1, dur_a, "acomodo_v1", vuelta, id_cam)
                    primera = False

                    # Chequeo (solo vuelta 1)
                    with self.cheq.request() as c:
                        yield c
                        yield self.env.timeout(U_rng(self.rng, *cfg["t_chequeo_pallet"]))
                        if self.rng.random() < cfg["p_defecto"]:
                            corregidos += 1
                            dur_corr = U_rng(self.rng, *cfg["t_correccion"])
                            yield from self._usar_grua(PRIO_R1, dur_corr, "correccion", vuelta, id_cam)
                            yield self.env.timeout(U_rng(self.rng, *cfg["t_chequeo_pallet"]))
                       

                    # Carga al camión (grúa)
                    dur_c = U_rng(self.rng, *cfg["t_carga_pallet"])
                    yield from self._usar_grua(PRIO_R1, dur_c, "carga", vuelta, id_cam)

                # Cierre por camión
                with self.parr.request() as p:
                    yield p
                    yield self.env.timeout(U_rng(self.rng, *cfg["t_ajuste_capacidad"]))
                    
                with self.movi.request() as m:
                    yield m
                    yield self.env.timeout(U_rng(self.rng, *cfg["t_mover_camion"]))

        else:
            # Vueltas ≥2: SOLO staging (acomodo en patio). Sin chequeo ni carga. Baja prioridad.
            for pal in pre_asignados:
                if pal["mixto"]:
                    print(f"[Debug] V{vuelta} C{id_cam}: staging MIXTO {pal.get('id','')}")
                    dur_a = U_rng(self.rng, *(cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]))
                    yield from self._usar_grua(PRIO_R2PLUS, dur_a, "acomodo_v2", vuelta, id_cam)
                    primera = False
                else:
                    print(f"[Debug] V{vuelta} C{id_cam}: staging COMPLETO {pal.get('id','')}")
                    dur_dc = U_rng(self.rng, *cfg["t_desp_completo"])
                    # Etiqueta nueva para que lo veas separado de 'pick_completo_v2'
                    yield from self._usar_grua(PRIO_R2PLUS, dur_dc, "despacho_completo_v2", vuelta, id_cam)
                    # Nota: no aplicamos 'acomodo_primera/otra' al completo aquí para mantener el cambio mínimo

        # 7) Log por camión
        t1 = self.env.now
        self.eventos.append({
            "vuelta": vuelta,
            "camion": id_cam,
            "pre_asignados": len(pre_asignados),
            "post_cargados": (len(post_lista) if vuelta == 1 else 0),
            "fusionados": (fusionados if vuelta == 1 else 0),
            "corregidos": (corregidos if vuelta == 1 else 0),
            "cajas_pre": sum(p["cajas"] for p in pre_asignados),
            "inicio_min": t0, "fin_min": t1,
            "inicio_hhmm": hhmm_dias(cfg["shift_start_min"] + t0),
            "fin_hhmm": hhmm_dias(cfg["shift_start_min"] + t1),
            "tiempo_min": t1 - t0,
            "modo": ("carga" if vuelta == 1 else "staging")
        })

# =============== Simulación con prioridad (gating de pick) ===============
def _resumir_grua(centro, cfg, total_fin):
    ops = centro.grua_ops
    by_vuelta = defaultdict(list)
    by_label = defaultdict(list)
    for o in ops:
        by_vuelta[o["vuelta"]].append(o)
        by_label[o["label"]].append(o)

    def pack(lst):
        if not lst:
            return {"ops": 0, "total_wait_min": 0, "mean_wait_min": 0, "max_wait_min": 0,
                    "total_hold_min": 0, "mean_hold_min": 0}
        waits = [x["wait"] for x in lst]
        holds = [x["hold"] for x in lst]
        return {
            "ops": len(lst),
            "total_wait_min": sum(waits),
            "mean_wait_min": (sum(waits)/len(waits) if waits else 0),
            "max_wait_min": (max(waits) if waits else 0),
            "total_hold_min": sum(holds),
            "mean_hold_min": (sum(holds)/len(holds) if holds else 0),
        }

    por_vuelta = []
    for v in sorted(by_vuelta):
        rec = pack(by_vuelta[v]); rec["vuelta"] = v
        por_vuelta.append(rec)

    por_label = {lbl: pack(lst) for lbl, lst in by_label.items()}

    total_hold = sum(o["hold"] for o in ops)
    horizon = max(total_fin, 1e-9)
    cap_total = cfg.get("cap_gruero", 4)
    util = total_hold / (cap_total * horizon)

    overall = {
        "ops": len(ops),
        "total_hold_min": total_hold,
        "total_wait_min": sum(o["wait"] for o in ops),
        "mean_wait_min": (sum(o["wait"] for o in ops)/len(ops) if ops else 0),
        "utilizacion_prom": util
    }
    return {"overall": overall, "por_vuelta": por_vuelta, "por_label": por_label}

def simular_turno_prioridad_rng(total_cajas, cfg, seed=None):
    rng = make_rng(seed)                 # RNG local. seed=None => diferente cada vez.
    env = simpy.Environment()

    pallets = generar_pallets_desde_cajas(total_cajas, cfg, rng)     # lista de dicts
    plan = construir_plan_desde_pallets(pallets, cfg, rng)           # [(vuelta, [lista_pallets_camion,...])]

    # Gating de pick por vuelta
    pick_gate = {}
    for (vuelta, asign) in plan:
        pick_gate[vuelta] = {"target": len(asign), "count": 0, "event": env.event(), "done_time": None}
    # vuelta 0 (ficticia) liberada para que R1 pueda empezar de inmediato
    pick_gate[0] = {"target": 0, "count": 0, "event": env.event(), "done_time": 0}
    pick_gate[0]["event"].succeed()

    centro = Centro(env, cfg, pick_gate, rng)

    # Lanzar procesos (cada camión en su vuelta)
    for (vuelta, asignaciones) in plan:
        for cam_id, pallets_cam in enumerate(asignaciones, start=1):
            env.process(centro.procesa_camion_vuelta(vuelta, cam_id, pallets_cam))

    env.run()

    # ---- Resumen por vuelta ----
    resumen_por_vuelta = []
    shift_end = cfg["shift_end_min"]

    for (vuelta, asignaciones) in plan:
        items = [e for e in centro.eventos if e["vuelta"] == vuelta]
        if not items:
            continue

        inicio_min   = min(e["inicio_min"] for e in items)              # inicio real (tras gate)
        fin_oper_min = max(e["fin_min"]    for e in items)              # fin operativo (incluye acomodo/carga)
        pick_fin_min = centro.pick_gate[vuelta]["done_time"]            # fin de PICK (gate liberado)

        # Fin "oficial": fin de PICK (vuelta 1 y vueltas >=2)
        fin_resumen_min = pick_fin_min if pick_fin_min is not None else fin_oper_min

        resumen_por_vuelta.append({
            "vuelta": vuelta,
            "camiones_en_vuelta": len(items),

            "inicio_hhmm": hhmm_dias(cfg["shift_start_min"] + inicio_min),
            "fin_hhmm":    hhmm_dias(cfg["shift_start_min"] + fin_resumen_min),
            "duracion_vuelta_min": fin_resumen_min - inicio_min,
            "overrun_min": max(0, fin_resumen_min - shift_end),

            # Marcas adicionales (para auditoría)
            "pick_fin_hhmm": hhmm_dias(cfg["shift_start_min"] + pick_fin_min) if pick_fin_min is not None else None,
            "fin_operativo_hhmm": hhmm_dias(cfg["shift_start_min"] + fin_oper_min),
            "duracion_operativa_min": fin_oper_min - inicio_min,

            # Métricas
            "pre_quemados_pallets": sum(e["pre_asignados"] for e in items),
            "pre_quemados_cajas":   sum(e["cajas_pre"]      for e in items),
            "post_cargados_pallets": sum(e["post_cargados"] for e in items),  # solo v1
            "fusionados":            sum(e["fusionados"]    for e in items),  # solo v1
            "modo": ("carga" if vuelta == 1 else "staging")
        })

    total_fin = max(e["fin_min"] for e in centro.eventos) if centro.eventos else 0

    # Resumen de grúa
    grua_metrics = _resumir_grua(centro, cfg, total_fin)

    return {
        "total_cajas": total_cajas,
        "pallets_pre_total": len(pallets),
        "vueltas": len(plan),
        "turno_inicio": hhmm_dias(cfg["shift_start_min"]),
        "turno_fin_nominal": hhmm_dias(cfg["shift_end_min"]),
        "turno_fin_real": hhmm_dias(cfg["shift_start_min"] + total_fin),
        "overrun_total_min": max(0, total_fin - cfg["shift_end_min"]),
        "resumen_vueltas": resumen_por_vuelta,
        "grua": grua_metrics,
    }

# ================= Ejemplo =================
if __name__ == "__main__":
    TOTAL_CAJAS = 20000

    # Variabilidad: usa seed=None; Reproducible: usa un entero (ej: 123)
    res = simular_turno_prioridad_rng(TOTAL_CAJAS, cfg, seed=None)

    print(f"Turno: {res['turno_inicio']} → nominal {res['turno_fin_nominal']} | real {res['turno_fin_real']}")
    print(f"Overrun total (min): {res['overrun_total_min']}")
    print(f"Cajas: {res['total_cajas']}  -> pallets pre-fusión: {res['pallets_pre_total']}")
    print(f"Vueltas: {res['vueltas']}")
    print("-- Vueltas --")
    for v in res["resumen_vueltas"]:
        print(v)

   