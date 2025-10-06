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
        try:
            ev = self.pick_gate[1]['event']
        except KeyError:
            return  # no hay vuelta 1 (caso raro)
        yield ev
        self.prio_acomodo_v1 = PRIO_R2PLUS

    def procesa_camion_vuelta(self, vuelta, id_cam, pallets_asignados):
        cfg = self.cfg

        # 1) Esperar gate si aplica
        if vuelta > 1:
            yield self.pick_gate[vuelta - 1]['event']

        # 2) Marca de inicio
        t0 = self.env.now

        # ==================== FASE A: PICK (SÓLO MIXTOS) ====================
        pre_asignados = pallets_asignados
        pick_list = [p for p in pre_asignados if p["mixto"]]

        for pal in pick_list:
            with self.pick.request() as r:
                q_pick = len(self.pick.queue); t_req_pick = self.env.now
                yield r
                t_prep_range = cfg["t_prep_mixto"]
                yield self.env.timeout(U_rng(self.rng, t_prep_range[0], t_prep_range[1]))

        # 3) Señal de fin de PICK
        self.pick_gate[vuelta]['count'] += 1
        if self.pick_gate[vuelta]['count'] >= self.pick_gate[vuelta]['target']:
            if not self.pick_gate[vuelta]['event'].triggered:
                self.pick_gate[vuelta]['done_time'] = self.env.now
                self.pick_gate[vuelta]['event'].succeed()

        # ==================== PROCESAMIENTO SECUENCIAL ====================
        corregidos = 0
        fusionados = 0

        if vuelta == 1:
            # *** SECUENCIAL CON FUSIÓN POST-CHEQUEO ***
            corregidos, fusionados = yield from self._procesar_vuelta_1_secuencial(vuelta, id_cam, pre_asignados)
        else:
            # Vueltas 2+ también secuenciales
            yield from self._procesar_staging_secuencial(vuelta, id_cam, pre_asignados)

        # Log por camión
        t1 = self.env.now
        cajas_pick_mixto_camion = sum(p["cajas"] for p in pre_asignados if p["mixto"])
        post_cargados = len(pre_asignados) - fusionados if vuelta == 1 else len(pre_asignados)
        
        self.eventos.append({
            "vuelta": vuelta,
            "camion": id_cam,
            "pre_asignados": len(pre_asignados),
            "post_cargados": post_cargados,
            "fusionados": fusionados,
            "corregidos": corregidos,
            "cajas_pre": sum(p["cajas"] for p in pre_asignados),
            "cajas_pick_mixto": cajas_pick_mixto_camion,
            "inicio_min": t0, "fin_min": t1,
            "inicio_hhmm": hhmm_dias(cfg["shift_start_min"] + t0),
            "fin_hhmm": hhmm_dias(cfg["shift_start_min"] + t1),
            "tiempo_min": t1 - t0,
            "modo": ("carga" if vuelta == 1 else "staging")
        })

    def _procesar_vuelta_1_secuencial(self, vuelta, id_cam, pallets_asignados):
        """
        Vuelta 1 SECUENCIAL pero con flujo correcto:
        1. Despacho+Acomodo de TODOS
        2. Chequeo de TODOS  
        3. Fusión basada en resultados
        4. Carga solo de finales
        """
        cfg = self.cfg
        corregidos = 0
        
        with self.patio_camiones.request() as slot:
            yield slot
            
            # ==================== FASE 1: DESPACHO + ACOMODO (TODOS) ====================
            primera = True
            for i, pal in enumerate(pallets_asignados):
                # Despacho (solo completos)
                if not pal["mixto"]:
                    t_desp_range = cfg["t_desp_completo"]
                    dur_dc = U_rng(self.rng, t_desp_range[0], t_desp_range[1])
                    yield from self._usar_grua(PRIO_R1, dur_dc, "despacho_completo", vuelta, id_cam)
                
                # Acomodo (todos)
                t_acomodo_range = cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]
                dur_a = U_rng(self.rng, t_acomodo_range[0], t_acomodo_range[1])
                yield from self._usar_grua(self.prio_acomodo_v1, dur_a, "acomodo_v1", vuelta, id_cam)
                primera = False
            
            # ==================== FASE 2: CHEQUEO (TODOS) ====================
            pallets_con_defecto = []
            for i, pal in enumerate(pallets_asignados):
                with self.cheq.request() as c:
                    yield c
                    t_chequeo_range = cfg["t_chequeo_pallet"]
                    yield self.env.timeout(U_rng(self.rng, t_chequeo_range[0], t_chequeo_range[1]))
                    
                    if self.rng.random() < cfg["p_defecto"]:
                        pallets_con_defecto.append((i, pal))
            
            # Correcciones
            corregidos = len(pallets_con_defecto)
            for i, pal in pallets_con_defecto:
                t_corr_range = cfg["t_correccion"]
                dur_corr = U_rng(self.rng, t_corr_range[0], t_corr_range[1])
                yield from self._usar_grua(PRIO_R1, dur_corr, "correccion", vuelta, id_cam)
                
                # Re-chequeo
                with self.cheq.request() as c:
                    yield c
                    yield self.env.timeout(U_rng(self.rng, t_chequeo_range[0], t_chequeo_range[1]))
            
            pallets_chequeados = pallets_asignados  # Todos ya chequeados
            cap_cam = sample_int_or_range_rng(self.rng, cfg["capacidad_pallets_camion"])
            fusionados = 0
            
            if len(pallets_chequeados) > cap_cam:
                exceso = len(pallets_chequeados) - cap_cam
                idx_mixtos = [i for i, p in enumerate(pallets_chequeados) if p["mixto"]]
                a_fusionar = min(exceso, len(idx_mixtos))
                
                if a_fusionar > 0:
                    quitar = set(self.rng.sample(idx_mixtos, a_fusionar))
                    pallets_finales = [p for i, p in enumerate(pallets_chequeados) if i not in quitar]
                    fusionados = a_fusionar
                else:
                    pallets_finales = pallets_chequeados[:cap_cam]
                    fusionados = len(pallets_chequeados) - cap_cam
            else:
                pallets_finales = pallets_chequeados
            
            # ==================== FASE 4: CARGA (SOLO FINALES) ====================
            for i, pal in enumerate(pallets_finales):
                t_carga_range = cfg["t_carga_pallet"]
                dur_c = U_rng(self.rng, t_carga_range[0], t_carga_range[1])
                yield from self._usar_grua(PRIO_R1, dur_c, "carga", vuelta, id_cam)
            
            # Cierre
            with self.parr.request() as p:
                yield p
                yield self.env.timeout(U_rng(self.rng, cfg["t_ajuste_capacidad"][0], cfg["t_ajuste_capacidad"][1]))
            with self.movi.request() as m:
                yield m
                yield self.env.timeout(U_rng(self.rng, cfg["t_mover_camion"][0], cfg["t_mover_camion"][1]))
        
        return corregidos, fusionados

    def _procesar_staging_secuencial(self, vuelta, id_cam, pre_asignados):
        cfg = self.cfg
        primera = True
        
        for pal in pre_asignados:
            if pal["mixto"]:
                t_acomodo_range = cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]
                dur_a = U_rng(self.rng, t_acomodo_range[0], t_acomodo_range[1])
                yield from self._usar_grua(PRIO_R2PLUS, dur_a, "acomodo_v2", vuelta, id_cam)
                primera = False
            else:
                t_desp_range = cfg["t_desp_completo"]
                dur_dc = U_rng(self.rng, t_desp_range[0], t_desp_range[1])
                yield from self._usar_grua(PRIO_R2PLUS, dur_dc, "despacho_completo_v2", vuelta, id_cam)