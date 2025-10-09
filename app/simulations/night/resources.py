# app/simulations/night_shift/resources.py
import simpy
from collections import defaultdict
from .utils import U_rng, sample_int_or_range_rng, hhmm_dias,sample_weibull_cajas,calcular_capacidad_objetiva
from .config import PRIO_R1, PRIO_R2PLUS, WEIBULL_CAJAS_PARAMS

class Centro:
    def __init__(self, env, cfg, pick_gate, rng, total_cajas_facturadas=None, num_camiones_estimado=None):
        self.env = env
        self.cfg = cfg
        self.pick_gate = pick_gate  # {v: {'target':N_cam, 'count':0, 'event':env.event(), 'done_time':None}}
        self.rng = rng

        self.capacidad_objetiva = None
        if total_cajas_facturadas and num_camiones_estimado:
            self.capacidad_objetiva = calcular_capacidad_objetiva(total_cajas_facturadas, num_camiones_estimado)

        # Recursos
        self.pick = simpy.Resource(env, capacity=cfg["cap_picker"])
        self.grua = simpy.PriorityResource(env, capacity=cfg["cap_gruero"])  # grúa única con cap=4
        self.cheq = simpy.Resource(env, capacity=cfg["cap_chequeador"])
        self.parr = simpy.Resource(env, capacity=cfg["cap_parrillero"])
        self.movi = simpy.Resource(env, capacity=cfg["cap_movilizador"])
        self.patio_camiones = simpy.Resource(env, capacity=cfg["cap_patio"])  # SOLO 1ª vuelta (carga)

        self.prio_acomodo_v1 = PRIO_R1   # prioridad alta para acomodo en 1ª vuelta
        env.process(self._rebalanceo_post_pick_v1())

        self.pausa_activa = False
        self.tiempo_pre_pausa = None
        
        # Programar salto automático de tiempo
        env.process(self._manejar_salto_almuerzo())

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

    def procesa_camion_vuelta(self, vuelta, camion_data):
        """Modificado para recibir datos del camión con ID"""
        camion_id = camion_data['camion_id']
        pallets_asignados = camion_data['pallets']
        
        cfg = self.cfg

        # 1) Esperar gate si aplica
        if vuelta > 1:
            yield self.pick_gate[vuelta - 1]['event']

        # 2) Marca de inicio
        t0 = self.env.now

        # ==================== FASE A: PICK (SÓLO MIXTOS) ====================
        pre_asignados = pallets_asignados
        pick_list = [p for p in pre_asignados if p["mixto"]]

        # Registrar cajas pickeadas por camión
        cajas_pickeadas_mixto = sum(p["cajas"] for p in pick_list)

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
            corregidos, fusionados = yield from self._procesar_vuelta_1_secuencial(vuelta, camion_id, pre_asignados)
        else:
            # Vueltas 2+ también secuenciales
            yield from self._procesar_staging_secuencial(vuelta, camion_id, pre_asignados)

        # Log por camión
        t1 = self.env.now
        cajas_pick_mixto_camion = sum(p["cajas"] for p in pre_asignados if p["mixto"])
        post_cargados = len(pre_asignados) - fusionados if vuelta == 1 else len(pre_asignados)
        
        evento = {
            "vuelta": vuelta,
            "camion_id": camion_id,  # Usar camion_id en lugar de camion
            "pre_asignados": len(pre_asignados),
            "post_cargados": post_cargados,
            "fusionados": fusionados,
            "corregidos": corregidos,
            "cajas_pre": sum(p["cajas"] for p in pre_asignados),
            "cajas_pick_mixto": cajas_pick_mixto_camion,
            "cajas_pickeadas_detalle": {
                "pallets_mixtos": [{"id": p["id"], "cajas": p["cajas"]} for p in pre_asignados if p["mixto"]],
                "pallets_completos": [{"id": p["id"], "cajas": p["cajas"]} for p in pre_asignados if not p["mixto"]],
                "total_cajas_mixtas": cajas_pick_mixto_camion,
                "total_cajas_completas": sum(p["cajas"] for p in pre_asignados if not p["mixto"])
            },
            "inicio_min": t0, "fin_min": t1,
            "inicio_hhmm": hhmm_dias(cfg["shift_start_min"] + t0),
            "fin_hhmm": hhmm_dias(cfg["shift_start_min"] + t1),
            "tiempo_min": t1 - t0,
            "modo": ("carga" if vuelta == 1 else "staging")
        }

        if hasattr(self, '_capacidades_usadas'):
            cap_info = self._capacidades_usadas
            evento.update({
                'capacidad_pallets_disponible': cap_info['capacidad_pallets_disponible'],
                'capacidad_cajas_disponible': cap_info['capacidad_cajas_disponible'],
                'utilizacion_pallets_pct': (post_cargados / cap_info['capacidad_pallets_disponible'] * 100) if cap_info['capacidad_pallets_disponible'] > 0 else 0,
                'utilizacion_cajas_pct': (sum(p["cajas"] for p in pre_asignados) / cap_info['capacidad_cajas_disponible'] * 100) if cap_info['capacidad_cajas_disponible'] > 0 else 0,
                'limitado_por': 'cajas' if cap_info['cajas_asignadas'] > cap_info['capacidad_cajas_disponible'] else ('pallets' if cap_info['pallets_asignados'] > cap_info['capacidad_pallets_disponible'] else 'ninguno')
            })
            delattr(self, '_capacidades_usadas')
        self.eventos.append(evento)
            

    def _procesar_vuelta_1_secuencial(self, vuelta, camion_id, pallets_asignados):
        """
        Vuelta 1 SECUENCIAL con flujo :
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
                    yield from self._usar_grua(PRIO_R1, dur_dc, "despacho_completo", vuelta, camion_id)
                
                # Acomodo (todos)
                t_acomodo_range = cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]
                dur_a = U_rng(self.rng, t_acomodo_range[0], t_acomodo_range[1])
                yield from self._usar_grua(self.prio_acomodo_v1, dur_a, "acomodo_v1", vuelta, camion_id)
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
                yield from self._usar_grua(PRIO_R1, dur_corr, "correccion", vuelta, camion_id)
                # Re-chequeo
                with self.cheq.request() as c:
                    yield c
                    yield self.env.timeout(U_rng(self.rng, t_chequeo_range[0], t_chequeo_range[1]))
            
            pallets_chequeados = pallets_asignados  # Todos ya chequeados
            cajas_totales = sum(p["cajas"] for p in pallets_chequeados)
            
            # *** USAR DISTRIBUCIÓN WEIBULL PARA CAPACIDAD DE CAJAS ***
            cap_cajas = sample_weibull_cajas(
                self.rng, 
                WEIBULL_CAJAS_PARAMS["alpha"],
                WEIBULL_CAJAS_PARAMS["beta"], 
                WEIBULL_CAJAS_PARAMS["gamma"],
            )

            cap_pallets = sample_int_or_range_rng(self.rng, cfg["capacidad_pallets_camion"])
            
             # Calcular cajas asignadas
            cajas_asignadas = sum(p["cajas"] for p in pallets_chequeados)
            
            # *** LÓGICA DE CARGA REALISTA ***
            fusionados = 0
            
            # Solo fusionar si realmente excede la capacidad
            if cajas_asignadas > cap_cajas or len(pallets_chequeados) > cap_pallets:
                # Estrategia: Mantener los pallets más eficientes (más cajas)
                pallets_ordenados = sorted(pallets_chequeados, key=lambda x: x["cajas"], reverse=True)
                
                pallets_finales = []
                cajas_cargadas = 0
                pallets_count = 0
                
                for pallet in pallets_ordenados:
                    puede_cargar = (
                        cajas_cargadas + pallet["cajas"] <= cap_cajas and 
                        pallets_count < cap_pallets
                    )
                    
                    if puede_cargar:
                        pallets_finales.append(pallet)
                        cajas_cargadas += pallet["cajas"]
                        pallets_count += 1
                    else:
                        fusionados += 1
                
            else:
                # Cabe todo sin problemas
                pallets_finales = pallets_chequeados
                cajas_cargadas = cajas_asignadas
            
            # ==================== FASE 4: CARGA (SOLO FINALES) ====================
            for i, pal in enumerate(pallets_finales):
                t_carga_range = cfg["t_carga_pallet"]
                dur_c = U_rng(self.rng, t_carga_range[0], t_carga_range[1])
                yield from self._usar_grua(PRIO_R1, dur_c, "carga", vuelta, camion_id)
            
            
            # Cierre
            with self.parr.request() as p:
                yield p
                yield self.env.timeout(U_rng(self.rng, cfg["t_ajuste_capacidad"][0], cfg["t_ajuste_capacidad"][1]))
            with self.movi.request() as m:
                yield m
                yield self.env.timeout(U_rng(self.rng, cfg["t_mover_camion"][0], cfg["t_mover_camion"][1]))
        
            self._capacidades_usadas = {
                'camion': camion_id,
                'vuelta': vuelta,
                'capacidad_pallets_disponible': cap_pallets,
                'capacidad_cajas_disponible': cap_cajas,
                'pallets_asignados': len(pallets_asignados),
                'cajas_asignadas': cajas_totales,
                'pallets_finales': len(pallets_finales),
                'cajas_finales': sum(p["cajas"] for p in pallets_finales),
                'fusionados': fusionados
            }

        return corregidos, fusionados

    def _procesar_staging_secuencial(self, vuelta, camion_id, pre_asignados):
        cfg = self.cfg
        primera = True
        
        for pal in pre_asignados:
            if pal["mixto"]:
                t_acomodo_range = cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]
                dur_a = U_rng(self.rng, t_acomodo_range[0], t_acomodo_range[1])
                yield from self._usar_grua(PRIO_R2PLUS, dur_a, "acomodo_v2", vuelta, camion_id)
                primera = False
            else:
                t_desp_range = cfg["t_desp_completo"]
                dur_dc = U_rng(self.rng, t_desp_range[0], t_desp_range[1])
                yield from self._usar_grua(PRIO_R2PLUS, dur_dc, "despacho_completo_v2", vuelta, camion_id)

    def _manejar_salto_almuerzo(self):
        """Maneja el salto automático de tiempo durante el almuerzo"""
        cfg = self.cfg
        almuerzo_inicio = cfg.get("almuerzo_inicio_min", 120)    # 2:00 AM
        almuerzo_fin = cfg.get("almuerzo_fin_min", 150)         # 2:30 AM  
        tiempo_salto = cfg.get("almuerzo_salto_min", 180)       # 3:00 AM (destino del salto)
        
        # Esperar hasta las 2:00 AM
        yield self.env.timeout(almuerzo_inicio)
        
        print(f"[ALMUERZO {hhmm_dias(almuerzo_inicio)}] 🍽️  PAUSA INICIADA - Operaciones suspendidas hasta las 3:00 AM")
        
        # Marcar pausa activa
        self.pausa_activa = True
        self.tiempo_pre_pausa = self.env.now
        
        # Esperar hasta las 2:30 AM
        yield self.env.timeout(almuerzo_fin - almuerzo_inicio)  # 30 minutos
        
        # *** SALTO DE TIEMPO: De 2:30 AM directo a 3:00 AM ***
        tiempo_actual = self.env.now  # Debería ser 150 (2:30 AM)
        tiempo_salto_necesario = tiempo_salto - tiempo_actual  # 180 - 150 = 30 min
        
        print(f"[ALMUERZO {hhmm_dias(tiempo_actual)}] ⏭️  SALTANDO TIEMPO - De 2:30 AM a 3:00 AM (+{tiempo_salto_necesario} min)")
        
        # Realizar el salto
        yield self.env.timeout(tiempo_salto_necesario)
        
        self.pausa_activa = False
        
        print(f"[ALMUERZO {hhmm_dias(self.env.now)}] ✅ OPERACIONES REANUDADAS - Trabajadores de vuelta")
