# app/simulations/night_shift/resources.py
import simpy
from collections import defaultdict
from .utils import U_rng, sample_int_or_range_rng, hhmm_dias
from .config import PRIO_R1, PRIO_R2PLUS

class Centro:
    def __init__(self, env, cfg, pick_gate, rng):
        self.env = env
        self.cfg = cfg
        self.pick_gate = pick_gate  # {v: {'target':N_cam, 'count':0, 'event':env.event(), 'done_time':None}}
        self.rng = rng

        # Recursos
        self.pick = simpy.Resource(env, capacity=cfg["cap_picker"])
        self.grua = simpy.PriorityResource(env, capacity=cfg["cap_gruero"])  # grúa única con cap=4
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
        try:
            ev = self.pick_gate[1]['event']
        except KeyError:
            return  # no hay vuelta 1 (caso raro)
        yield ev
        self.prio_acomodo_v1 = PRIO_R2PLUS
        print(f"[Rebalance] t={self.env.now:.2f} fin PICK V1 → acomodo_v1 ahora PRIO_R2PLUS")

    def procesa_camion_vuelta(self, vuelta, id_cam, pallets_asignados):
        """
        Tu lógica exacta:
        Gating de pick: Vuelta k+1 comienza PICK cuando vuelta k terminó su PICK.
        Vuelta 1: PICK (sólo mixtos) → FUSIÓN (post-pick) → despacho completos + acomodo + chequeo + carga.
        Vueltas ≥2: PICK (sólo mixtos) + staging (acomodo_v2 / despacho_completo_v2). Sin chequeo ni carga.
        """
        cfg = self.cfg

        # 1) Esperar gate si aplica (vuelta>1 espera fin del PICK de la anterior)
        if vuelta > 1:
            yield self.pick_gate[vuelta - 1]['event']

        # 2) Marca de inicio (después del gate)
        t0 = self.env.now

        # -------------------- FASE A: PICK (SÓLO MIXTOS) --------------------
        pre_asignados = pallets_asignados
        pick_list = [p for p in pre_asignados if p["mixto"]]  # SOLO pallets para pickeo

        for pal in pick_list:
            with self.pick.request() as r:
                q_pick = len(self.pick.queue); t_req_pick = self.env.now
                yield r
                print(f"[Debug] V{vuelta} C{id_cam}: WAIT pick={self.env.now - t_req_pick:.2f} (cola={q_pick})")
                t_prep_range = cfg["t_prep_mixto"]
                yield self.env.timeout(U_rng(self.rng, t_prep_range[0], t_prep_range[1]))

        # 3) Señal de fin de PICK para esta vuelta (gating hacia la siguiente vuelta)
        self.pick_gate[vuelta]['count'] += 1
        if self.pick_gate[vuelta]['count'] >= self.pick_gate[vuelta]['target']:
            if not self.pick_gate[vuelta]['event'].triggered:
                self.pick_gate[vuelta]['done_time'] = self.env.now
                self.pick_gate[vuelta]['event'].succeed()

        # -------------------- FASE B: FUSIÓN (post-pick, SOLO V1) --------------------
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
                    print(f"[Debug] V{vuelta} C{id_cam}: post-pick FUSION pre {len(pre_asignados)} -> post {len(post_lista)} (fusionados {fusionados})")
                else:
                    post_lista = pre_asignados[:cap_cam]
                    fusionados = 0
                    print(f"[Debug] V{vuelta} C{id_cam}: post-pick FUSION pre {len(pre_asignados)} -> post {len(post_lista)} (no mixtos para fusionar)")

        # -------------------- FASE C: Post-pick (operaciones con grúa) --------------------
        corregidos = 0
        primera = True

        if vuelta == 1:
            # 1ª vuelta: ocupar patio y completar despacho de completos + acomodo + chequeo + carga
            with self.patio_camiones.request() as slot:
                yield slot

                for pal in post_lista:
                    # Para COMPLETOS en V1: traer el pallet completo (despacho) con grúa
                    if not pal["mixto"]:
                        print(f"[Debug] V{vuelta} C{id_cam}: despacho COMPLETO {pal.get('id','')}")
                        t_desp_range = cfg["t_desp_completo"]
                        dur_dc = U_rng(self.rng, t_desp_range[0], t_desp_range[1])
                        yield from self._usar_grua(PRIO_R1, dur_dc, "pick_completo", vuelta, id_cam)

                    # Acomodo (grúa)
                    t_acomodo_range = cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]
                    dur_a = U_rng(self.rng, t_acomodo_range[0], t_acomodo_range[1])
                    yield from self._usar_grua(self.prio_acomodo_v1, dur_a, "acomodo_v1", vuelta, id_cam)
                    primera = False

                    # Chequeo (solo vuelta 1)
                    with self.cheq.request() as c:
                        yield c
                        t_chequeo_range = cfg["t_chequeo_pallet"]
                        yield self.env.timeout(U_rng(self.rng, t_chequeo_range[0], t_chequeo_range[1]))
                        if self.rng.random() < cfg["p_defecto"]:
                            corregidos += 1
                            print(f"[Debug] V{vuelta} C{id_cam}: CORRECCION {pal.get('id','')}")
                            t_corr_range = cfg["t_correccion"]
                            dur_corr = U_rng(self.rng, t_corr_range[0], t_corr_range[1])
                            yield from self._usar_grua(PRIO_R1, dur_corr, "correccion", vuelta, id_cam)
                            yield self.env.timeout(U_rng(self.rng, t_chequeo_range[0], t_chequeo_range[1]))

                    # Carga al camión (grúa)
                    print(f"[Debug] V{vuelta} C{id_cam}: carga {pal.get('id','')}")
                    t_carga_range = cfg["t_carga_pallet"]
                    dur_c = U_rng(self.rng, t_carga_range[0], t_carga_range[1])
                    yield from self._usar_grua(PRIO_R1, dur_c, "carga", vuelta, id_cam)

                # Cierre por camión
                with self.parr.request() as p:
                    yield p
                    t_ajuste_range = cfg["t_ajuste_capacidad"]
                    yield self.env.timeout(U_rng(self.rng, t_ajuste_range[0], t_ajuste_range[1]))
                with self.movi.request() as m:
                    yield m
                    t_mover_range = cfg["t_mover_camion"]
                    yield self.env.timeout(U_rng(self.rng, t_mover_range[0], t_mover_range[1]))

        else:
            # Vueltas ≥2: SOLO staging. Mixto: acomodo_v2; Completo: despacho_completo_v2
            for pal in pre_asignados:
                if pal["mixto"]:
                    print(f"[Debug] V{vuelta} C{id_cam}: staging MIXTO {pal.get('id','')}")
                    t_acomodo_range = cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]
                    dur_a = U_rng(self.rng, t_acomodo_range[0], t_acomodo_range[1])
                    yield from self._usar_grua(PRIO_R2PLUS, dur_a, "acomodo_v2", vuelta, id_cam)
                    primera = False
                else:
                    print(f"[Debug] V{vuelta} C{id_cam}: staging COMPLETO {pal.get('id','')}")
                    t_desp_range = cfg["t_desp_completo"]
                    dur_dc = U_rng(self.rng, t_desp_range[0], t_desp_range[1])
                    yield from self._usar_grua(PRIO_R2PLUS, dur_dc, "despacho_completo_v2", vuelta, id_cam)

        # 7) Log por camión (incluye cajas pickeadas MIXTAS para ICE)
        t1 = self.env.now
        cajas_pick_mixto_camion = sum(p["cajas"] for p in pre_asignados if p["mixto"])
        self.eventos.append({
            "vuelta": vuelta,
            "camion": id_cam,
            "pre_asignados": len(pre_asignados),
            "post_cargados": (len(post_lista) if vuelta == 1 else 0),
            "fusionados": (fusionados if vuelta == 1 else 0),
            "corregidos": (corregidos if vuelta == 1 else 0),
            "cajas_pre": sum(p["cajas"] for p in pre_asignados),
            "cajas_pick_mixto": cajas_pick_mixto_camion,  # SOLO mixtas (para ICE)
            "inicio_min": t0, "fin_min": t1,
            "inicio_hhmm": hhmm_dias(cfg["shift_start_min"] + t0),
            "fin_hhmm": hhmm_dias(cfg["shift_start_min"] + t1),
            "tiempo_min": t1 - t0,
            "modo": ("carga" if vuelta == 1 else "staging")
        })