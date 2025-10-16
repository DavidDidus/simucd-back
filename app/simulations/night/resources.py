import simpy
import numpy as np
from collections import defaultdict
from .utils import U_rng, sample_int_or_range_rng, hhmm_dias, sample_weibull_cajas, calcular_capacidad_objetiva, sample_chisquared_prep_mixto, sample_tiempo_carga_pallet, sample_tiempo_despacho_completo, sample_tiempo_chequeo_unitario
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
        self.tiempos_chequeo_detallados = []
        self.metricas_chequeadores = {
            'operaciones_totales': 0,
            'tiempo_total_activo': 0,
            'tiempo_total_espera': 0,
            'pallets_chequeados': 0,
            'por_camion': [],
            'por_vuelta': defaultdict(lambda: {
                'operaciones': 0,
                'tiempo_activo': 0,
                'tiempo_espera': 0,
                'pallets': 0
            })
        }
        
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

    def _chequear_pallet_individual(self, vuelta, camion_id, pallet, pallet_idx, total_pallets):
        """
        🆕 Chequea UN SOLO pallet y libera el chequeador
        Registra métricas detalladas de la operación
        
        Args:
            vuelta: número de vuelta
            camion_id: ID del camión
            pallet: diccionario con info del pallet
            pallet_idx: índice del pallet (1-based)
            total_pallets: total de pallets del camión
            
        Returns:
            tuple: (tiempo_chequeo, tiempo_espera, tiene_defecto)
        """
        cfg = self.cfg
        
        t_request = self.env.now
        
        with self.cheq.request() as c:
            yield c
            
            t_espera = self.env.now - t_request
            t_inicio_chequeo = self.env.now
            
            # Muestrear tiempo de chequeo para este pallet
            tiempo_chequeo = sample_tiempo_chequeo_unitario(self.rng)
            
            # Realizar chequeo
            yield self.env.timeout(tiempo_chequeo)
            
            t_fin_chequeo = self.env.now
            
            # Determinar si tiene defecto
            tiene_defecto = self.rng.random() < cfg["p_defecto"]
            
            # 🆕 Log detallado del chequeo
            detalle_chequeo = {
                'vuelta': vuelta,
                'camion': camion_id,
                'pallet_id': pallet['id'],
                'pallet_idx': pallet_idx,
                'total_pallets_camion': total_pallets,
                'es_mixto': pallet.get('mixto', False),
                'cajas': pallet.get('cajas', 0),
                'tiempo_espera_min': t_espera,
                'tiempo_chequeo_min': tiempo_chequeo,
                'tiempo_inicio': t_inicio_chequeo,
                'tiempo_fin': t_fin_chequeo,
                'tiene_defecto': tiene_defecto,
                'timestamp': hhmm_dias(t_inicio_chequeo)
            }
            
            self.tiempos_chequeo_detallados.append(detalle_chequeo)
            
            # 🆕 Actualizar métricas globales de chequeadores
            self.metricas_chequeadores['operaciones_totales'] += 1
            self.metricas_chequeadores['tiempo_total_activo'] += tiempo_chequeo
            self.metricas_chequeadores['tiempo_total_espera'] += t_espera
            self.metricas_chequeadores['pallets_chequeados'] += 1
            
            # Métricas por vuelta
            vuelta_stats = self.metricas_chequeadores['por_vuelta'][vuelta]
            vuelta_stats['operaciones'] += 1
            vuelta_stats['tiempo_activo'] += tiempo_chequeo
            vuelta_stats['tiempo_espera'] += t_espera
            vuelta_stats['pallets'] += 1
            
            # Log en consola para primer y último pallet
            if pallet_idx == 1 or pallet_idx == total_pallets:
                print(f"[CHEQUEO V{vuelta}] Camión {camion_id} pallet {pallet_idx}/{total_pallets}: "
                      f"Espera={t_espera:.2f}min, Chequeo={tiempo_chequeo:.2f}min, "
                      f"Defecto={'SÍ' if tiene_defecto else 'NO'}")
        
        return tiempo_chequeo, t_espera, tiene_defecto

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
                    
                    yield self.env.timeout(tiempo_prep)
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
            corregidos, fusionados = yield from self._procesar_vuelta_1_paralelo(vuelta, camion_id, pre_asignados)
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
                'pallets_chequeados': cap_info.get('pallets_chequeados', 0),
                'tiempo_espera_chequeo_min': cap_info.get('tiempo_espera_total', 0)
            })
            delattr(self, '_capacidades_usadas')
            
        self.eventos.append(evento)

    def _procesar_vuelta_1_paralelo(self, vuelta, camion_id, pallets_asignados):
        """
        🆕 Vuelta 1 con CHEQUEO PARALELO AL ACOMODO
        Cada pallet inicia su chequeo apenas termina de ser acomodado
        """
        cfg = self.cfg
        corregidos = 0
        
        t_inicio_camion = self.env.now
        
        with self.patio_camiones.request() as slot:
            yield slot

            # ==================== FASE 1: DESPACHO + ACOMODO + CHEQUEO EN PARALELO ====================
            t_inicio_fase_1 = self.env.now
            
            # 🆕 Lista para trackear procesos de chequeo en paralelo
            procesos_acomodo_chequeo = []
        
            print(f"[FASE 1 V{vuelta}] Camión {camion_id}: Iniciando procesamiento paralelo de {len(pallets_asignados)} pallets")
            
            # 🔧 INICIAR TODOS LOS PROCESOS EN PARALELO
            for i, pal in enumerate(pallets_asignados):
                proceso = self.env.process(
                    self._procesar_pallet_completo(vuelta, camion_id, pal, i, len(pallets_asignados), i == 0)
                )
                procesos_acomodo_chequeo.append(proceso)
            
            # Esperar a que TODOS terminen (acomodo + chequeo)
            resultados = yield simpy.AllOf(self.env, procesos_acomodo_chequeo)
            
            # Extraer información de resultados
            pallets_chequeados_info = [r for r in resultados.values()]
            
            t_fin_fase_1 = self.env.now
            tiempo_fase_1 = t_fin_fase_1 - t_inicio_fase_1
            
            # 🆕 Calcular estadísticas de chequeo
            tiempos_chequeo = [info['tiempo_chequeo'] for info in pallets_chequeados_info]
            tiempos_espera = [info['tiempo_espera'] for info in pallets_chequeados_info]
            pallets_con_defecto = [(info['idx'], info['pallet']) for info in pallets_chequeados_info if info['tiene_defecto']]
            
            tiempo_chequeo_activo = sum(tiempos_chequeo)
            tiempo_espera_total = sum(tiempos_espera)
            tiempo_espera_promedio = np.mean(tiempos_espera) if tiempos_espera else 0
            tasa_chequeo_promedio = len(pallets_asignados) / tiempo_chequeo_activo if tiempo_chequeo_activo > 0 else 0
            
            print(f"[FASE 1 V{vuelta}] Camión {camion_id}: ✅ Completada en {tiempo_fase_1:.2f} min "
                  f"(chequeo activo: {tiempo_chequeo_activo:.2f}, espera prom: {tiempo_espera_promedio:.2f}, "
                  f"defectos: {len(pallets_con_defecto)})")
            
            # 🆕 Registrar métricas del camión para chequeadores
            self.metricas_chequeadores['por_camion'].append({
                'vuelta': vuelta,
                'camion': camion_id,
                'pallets_chequeados': len(pallets_asignados),
                'tiempo_total_fase': tiempo_fase_1,
                'tiempo_activo': tiempo_chequeo_activo,
                'tiempo_espera_total': tiempo_espera_total,
                'tiempo_espera_promedio': tiempo_espera_promedio,
                'defectos_encontrados': len(pallets_con_defecto),
                'tasa_pallets_por_min': tasa_chequeo_promedio,
                'modo_paralelo': True  # 🆕 Identificar que usó modo paralelo
            })
            
            # ==================== FASE 2: CORRECCIONES ====================
            t_inicio_correccion = self.env.now
            corregidos = len(pallets_con_defecto)
            
            if corregidos > 0:
                print(f"[CORRECCIÓN V{vuelta}] Camión {camion_id}: Corrigiendo {corregidos} pallets defectuosos")
            
            for idx, pal in pallets_con_defecto:
                # Corrección con grúa
                t_corr_range = cfg["t_correccion"]
                dur_corr = U_rng(self.rng, t_corr_range[0], t_corr_range[1])
                yield from self._usar_grua(PRIO_R1, dur_corr, "correccion", vuelta, camion_id)
                
                # Re-chequeo del pallet corregido (secuencial, no paralelo)
                tiempo_rechequeo, tiempo_espera_rechequeo, _ = yield from self._chequear_pallet_individual(
                    vuelta, camion_id, pal, idx + 1, len(pallets_asignados)
                )
            
            t_fin_correccion = self.env.now
            tiempo_correccion = t_fin_correccion - t_inicio_correccion
            
            # ==================== FASE 3: CAPACIDADES Y FUSIÓN ====================
            t_inicio_fusion = self.env.now
            
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
            
            t_fin_fusion = self.env.now
            tiempo_fusion = t_fin_fusion - t_inicio_fusion
            
            # ==================== FASE 4: CARGA ====================
            t_inicio_carga = self.env.now
            
            for i, pal in enumerate(pallets_finales):
                dur_c = sample_tiempo_carga_pallet(self.rng)
                yield from self._usar_grua(PRIO_R1, dur_c, "carga", vuelta, camion_id)
            
            t_fin_carga = self.env.now
            tiempo_carga = t_fin_carga - t_inicio_carga
            
            # ==================== FASE 5: CIERRE ====================
            t_inicio_cierre = self.env.now
            
            with self.parr.request() as p:
                yield p
                yield self.env.timeout(U_rng(self.rng, cfg["t_ajuste_capacidad"][0], cfg["t_ajuste_capacidad"][1]))
            with self.movi.request() as m:
                yield m
                yield self.env.timeout(U_rng(self.rng, cfg["t_mover_camion"][0], cfg["t_mover_camion"][1]))
            
            t_fin_cierre = self.env.now
            tiempo_cierre = t_fin_cierre - t_inicio_cierre
            
            # Guardar estadísticas detalladas
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
                'tiempo_chequeo_total': tiempo_fase_1,  # Tiempo total incluye chequeo
                'tiempo_chequeo_activo': tiempo_chequeo_activo,
                'tasa_chequeo_promedio': tasa_chequeo_promedio,
                'pallets_chequeados': len(pallets_asignados),
                'tiempo_espera_chequeo_promedio': tiempo_espera_promedio,
                'tiempo_fase_1_con_chequeo': tiempo_fase_1,  # 🆕 Nuevo: tiempo combinado
                'tiempo_correccion': tiempo_correccion,
                'tiempo_fusion': tiempo_fusion,
                'tiempo_carga': tiempo_carga,
                'tiempo_cierre': tiempo_cierre,
                'tiempo_total_camion': t_fin_cierre - t_inicio_camion,
                'modo_paralelo': True  # 🆕 Identificar que usó chequeo paralelo
            }

        return corregidos, fusionados

    def _procesar_staging_secuencial(self, vuelta, camion_id, pre_asignados):
        """Vuelta 2+ STAGING - PICK ya completado"""
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


    def _procesar_pallet_completo(self, vuelta, camion_id, pallet, idx, total, es_primero):
        """🆕 Procesa UN pallet: despacho/acomodo + chequeo en paralelo"""
        cfg = self.cfg
        
        # 1. Despacho (solo completos)
        if not pallet["mixto"]:
            dur_dc = sample_tiempo_despacho_completo(self.rng)
            yield from self._usar_grua(PRIO_R1, dur_dc, "despacho_completo", vuelta, camion_id)
        
        # 2. Acomodo
        t_acomodo_range = cfg["t_acomodo_primera"] if es_primero else cfg["t_acomodo_otra"]
        dur_a = U_rng(self.rng, t_acomodo_range[0], t_acomodo_range[1])
        yield from self._usar_grua(self.prio_acomodo_v1, dur_a, "acomodo_v1", vuelta, camion_id)
        
        # 3. Chequeo INMEDIATO después del acomodo
        tiempo_chequeo, tiempo_espera, tiene_defecto = yield from self._chequear_pallet_individual(
            vuelta, camion_id, pallet, idx + 1, total
        )
        
        return {
            'idx': idx,
            'pallet': pallet,
            'tiempo_chequeo': tiempo_chequeo,
            'tiempo_espera': tiempo_espera,
            'tiene_defecto': tiene_defecto
        }