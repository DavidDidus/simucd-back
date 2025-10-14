# app/simulations/night/resources.py
import simpy
import numpy as np
from collections import defaultdict
from .utils import U_rng, sample_int_or_range_rng, hhmm_dias, sample_weibull_cajas, calcular_capacidad_objetiva, calcular_tiempo_chequeo_lognormal, sample_chisquared_prep_mixto, sample_tiempo_carga_pallet, sample_tiempo_despacho_completo
from .config import PRIO_R1, PRIO_R2PLUS, WEIBULL_CAJAS_PARAMS,CHISQUARED_PREP_MIXTO

class Centro:
    def __init__(self, env, cfg, pick_gate, rng, total_cajas_facturadas=None, num_camiones_estimado=None):
        self.env = env
        self.cfg = cfg
        self.pick_gate = pick_gate
        self.rng = rng

        self.capacidad_objetiva = None
        if total_cajas_facturadas and num_camiones_estimado:
            self.capacidad_objetiva = calcular_capacidad_objetiva(total_cajas_facturadas, num_camiones_estimado)

        # Recursos
        self.pick = simpy.Resource(env, capacity=cfg["cap_picker"])
        self.grua = simpy.PriorityResource(env, capacity=cfg["cap_gruero"])
        self.cheq = simpy.Resource(env, capacity=cfg["cap_chequeador"])
        self.parr = simpy.Resource(env, capacity=cfg["cap_parrillero"])
        self.movi = simpy.Resource(env, capacity=cfg["cap_movilizador"])
        self.patio_camiones = simpy.Resource(env, capacity=cfg["cap_patio"])

        self.prio_acomodo_v1 = PRIO_R1
        env.process(self._rebalanceo_post_pick_v1())

        self.pausa_almuerzo_activa = False
        self.tiempo_inicio_almuerzo = None
        self.tiempo_fin_almuerzo = None
        
        env.process(self._manejar_salto_almuerzo())

        # Logs
        self.eventos = []
        self.grua_ops = []
        self.tiempos_prep_mixto = []
        
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
            return
        yield ev
        self.prio_acomodo_v1 = PRIO_R2PLUS

    def procesa_camion_vuelta(self, vuelta, camion_data):
        """Procesamiento de camión - PICK se ejecuta ANTES de otras operaciones"""
        camion_id = camion_data['camion_id']
        pallets_asignados = camion_data['pallets']
        
        cfg = self.cfg

        # 1) Esperar gate de vuelta anterior (solo si vuelta > 1)
        if vuelta > 1:
            print(f"[VUELTA {vuelta}] Camión {camion_id}: Esperando gate de vuelta {vuelta-1}...")
            yield self.pick_gate[vuelta - 1]['event']
            print(f"[VUELTA {vuelta}] Camión {camion_id}: ✅ Gate activado, iniciando operaciones")

        # 2) Marca de inicio
        t0 = self.env.now

        # ==================== FASE A: PICK (TODOS LOS MIXTOS) ====================
        pre_asignados = pallets_asignados
        pick_list = [p for p in pre_asignados if p["mixto"]]

        if pick_list:
            #print(f"[PICK V{vuelta}] Camión {camion_id}: Iniciando PICK de {len(pick_list)} pallets mixtos (t={self.env.now:.1f})")
            
            tiempos_prep_este_camion = []

            for idx, pal in enumerate(pick_list):
                with self.pick.request() as r:
                    t_wait_start = self.env.now
                    yield r
                    t_wait = self.env.now - t_wait_start

                    tiempo_prep = sample_chisquared_prep_mixto(
                        self.rng,
                        CHISQUARED_PREP_MIXTO["df"],
                        CHISQUARED_PREP_MIXTO["scale"]
                    )

                    tiempos_prep_este_camion.append(tiempo_prep)
                    self.tiempos_prep_mixto.append({
                        "vuelta": vuelta, 
                        "camion": camion_id, 
                        "pallet_idx": idx + 1, 
                        "tiempo_prep_min": tiempo_prep,
                        "tiempo_espera_min": t_wait
                    })

                    #if idx == 0 or idx == len(pick_list) - 1:  # Log primer y último pallet
                        #print(f"[PICK V{vuelta}] Camión {camion_id} pallet {idx+1}/{len(pick_list)}: "
                         #     f"Prep={tiempo_prep:.2f}min, Espera={t_wait:.1f}min")
                    
                    yield self.env.timeout(tiempo_prep)
            
            tiempo_prep_promedio = np.mean(tiempos_prep_este_camion)
            #print(f"[PICK V{vuelta}] Camión {camion_id}: ✅ PICK completado (t={self.env.now:.1f}, "
             #     f"duración={self.env.now - t0:.1f}min, prep_prom={tiempo_prep_promedio:.2f}min)")
        else:
            print(f"[PICK V{vuelta}] Camión {camion_id}: Sin pallets mixtos, saltando PICK")

        # 3) Señal de fin de PICK para este camión
        self.pick_gate[vuelta]['count'] += 1
        if self.pick_gate[vuelta]['count'] >= self.pick_gate[vuelta]['target']:
            if not self.pick_gate[vuelta]['event'].triggered:
                self.pick_gate[vuelta]['done_time'] = self.env.now
                self.pick_gate[vuelta]['event'].succeed()
                print(f"[GATE V{vuelta}] ✅ ACTIVADO - Todos los camiones de vuelta {vuelta} completaron PICK (t={self.env.now:.1f})")

        # ==================== PROCESAMIENTO POST-PICK ====================
        corregidos = 0
        fusionados = 0

        if vuelta == 1:
            corregidos, fusionados = yield from self._procesar_vuelta_1_secuencial(vuelta, camion_id, pre_asignados)
        else:
            yield from self._procesar_staging_secuencial(vuelta, camion_id, pre_asignados)

        # Log por camión
        t1 = self.env.now
        cajas_pick_mixto_camion = sum(p["cajas"] for p in pre_asignados if p["mixto"])
        post_cargados = len(pre_asignados) - fusionados if vuelta == 1 else len(pre_asignados)
        
        evento = {
            "vuelta": vuelta,
            "camion_id": camion_id,
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
                'limitado_por': 'cajas' if cap_info.get('cajas_asignadas', 0) > cap_info['capacidad_cajas_disponible'] else ('pallets' if cap_info.get('pallets_asignados', 0) > cap_info['capacidad_pallets_disponible'] else 'ninguno'),
                'tiempo_chequeo_lognormal_min': cap_info.get('tiempo_chequeo_total', 0),
                'tasa_chequeo_pallets_por_min': cap_info.get('tasa_chequeo_promedio', 0),
                'pallets_chequeados': cap_info.get('pallets_chequeados', 0)
            })
            delattr(self, '_capacidades_usadas')
            
        self.eventos.append(evento)

    def _procesar_vuelta_1_secuencial(self, vuelta, camion_id, pallets_asignados):
        """
        Vuelta 1 SECUENCIAL - PICK ya completado en procesa_camion_vuelta
        """
        cfg = self.cfg
        corregidos = 0
        
        with self.patio_camiones.request() as slot:
            yield slot

            # ==================== FASE 1: DESPACHO + ACOMODO ====================
            primera = True
            for i, pal in enumerate(pallets_asignados):
                if not pal["mixto"]:
                    # 🆕 USAR DISTRIBUCIÓN LOGNORMAL PARA DESPACHO DE COMPLETO
                    dur_dc = sample_tiempo_despacho_completo(self.rng)
                    print(f"[DESPACHO] Camión {camion_id}, Pallet completo {i+1}: {dur_dc:.2f} min")
                    yield from self._usar_grua(PRIO_R1, dur_dc, "despacho_completo", vuelta, camion_id)
                
                t_acomodo_range = cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]
                dur_a = U_rng(self.rng, t_acomodo_range[0], t_acomodo_range[1])
                yield from self._usar_grua(self.prio_acomodo_v1, dur_a, "acomodo_v1", vuelta, camion_id)
                primera = False
            
            # ==================== FASE 2: CHEQUEO ====================
            num_pallets_total = len(pallets_asignados)
            tiempo_chequeo_total, tasa_chequeo_promedio = calcular_tiempo_chequeo_lognormal(num_pallets_total, self.rng)
            
            with self.cheq.request() as c:
                yield c
                yield self.env.timeout(tiempo_chequeo_total)
            
            # Determinar defectos
            pallets_con_defecto = []
            for i, pal in enumerate(pallets_asignados):
                if self.rng.random() < cfg["p_defecto"]:
                    pallets_con_defecto.append((i, pal))
            
            # Correcciones
            corregidos = len(pallets_con_defecto)
            for i, pal in pallets_con_defecto:
                t_corr_range = cfg["t_correccion"]
                dur_corr = U_rng(self.rng, t_corr_range[0], t_corr_range[1])
                yield from self._usar_grua(PRIO_R1, dur_corr, "correccion", vuelta, camion_id)
                
                tiempo_rechequeo, _ = calcular_tiempo_chequeo_lognormal(1, self.rng)
                with self.cheq.request() as c:
                    yield c
                    yield self.env.timeout(tiempo_rechequeo)
            
            # ==================== FASE 3: CAPACIDADES Y FUSIÓN ====================
            pallets_chequeados = pallets_asignados
            cajas_totales = sum(p["cajas"] for p in pallets_chequeados)
            
            cap_cajas = sample_weibull_cajas(
                self.rng, 
                WEIBULL_CAJAS_PARAMS["alpha"],
                WEIBULL_CAJAS_PARAMS["beta"], 
                WEIBULL_CAJAS_PARAMS["gamma"],
            )

            cap_pallets = sample_int_or_range_rng(self.rng, cfg["capacidad_pallets_camion"])
            cajas_asignadas = sum(p["cajas"] for p in pallets_chequeados)
            
            fusionados = 0
            if cajas_asignadas > cap_cajas or len(pallets_chequeados) > cap_pallets:
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
                pallets_finales = pallets_chequeados
                cajas_cargadas = cajas_asignadas
            
            # ==================== FASE 4: CARGA ====================
            for i, pal in enumerate(pallets_finales):
                # *** USAR DISTRIBUCIÓN LOGNORMAL PARA TIEMPO DE CARGA ***
                dur_c = sample_tiempo_carga_pallet(self.rng)
                print(f"[CARGA] Camión {camion_id}, Pallet {i+1}/{len(pallets_finales)}: {dur_c:.2f} min")
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
                'fusionados': fusionados,
                'tiempo_chequeo_total': tiempo_chequeo_total,
                'tasa_chequeo_promedio': tasa_chequeo_promedio,
                'pallets_chequeados': num_pallets_total
            }

        return corregidos, fusionados

    def _procesar_staging_secuencial(self, vuelta, camion_id, pre_asignados):
        """Vuelta 2+ STAGING - PICK ya completado en procesa_camion_vuelta"""
        cfg = self.cfg
        primera = True

        print(f"[STAGING V{vuelta}] Camión {camion_id}: Iniciando staging de {len(pre_asignados)} pallets")
        
        for pal in pre_asignados:
            if pal["mixto"]:
                t_acomodo_range = cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]
                dur_a = U_rng(self.rng, t_acomodo_range[0], t_acomodo_range[1])
                yield from self._usar_grua(PRIO_R2PLUS, dur_a, "acomodo_v2", vuelta, camion_id)
                primera = False
            else:
                dur_dc = sample_tiempo_despacho_completo(self.rng)
                print(f"[DESPACHO V{vuelta}] Camión {camion_id}, Pallet completo: {dur_dc:.2f} min")
                yield from self._usar_grua(PRIO_R2PLUS, dur_dc, "despacho_completo_v2", vuelta, camion_id)
                
        print(f"[STAGING V{vuelta}] Camión {camion_id}: ✅ Staging completado")

    def _manejar_salto_almuerzo(self):
        """Manejo simplificado del salto de almuerzo"""
        cfg = self.cfg
        almuerzo_inicio = cfg.get("almuerzo_inicio_min", 120)
        tiempo_salto = cfg.get("almuerzo_salto_min", 150)
        
        yield self.env.timeout(almuerzo_inicio)
        print(f"[ALMUERZO {hhmm_dias(almuerzo_inicio)}] 🍽️  PAUSA INICIADA")
        
        self.pausa_almuerzo_activa = True
        self.tiempo_inicio_almuerzo = self.env.now
        
        tiempo_salto_necesario = tiempo_salto - self.env.now
        print(f"[ALMUERZO {hhmm_dias(self.env.now)}] ⏭️  SALTANDO {tiempo_salto_necesario} minutos")
        
        yield self.env.timeout(tiempo_salto_necesario)
        
        self.pausa_almuerzo_activa = False
        self.tiempo_fin_almuerzo = self.env.now
        
        print(f"[ALMUERZO {hhmm_dias(self.env.now)}] ✅ OPERACIONES REANUDADAS")