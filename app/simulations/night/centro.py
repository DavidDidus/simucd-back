# app/simulations/night_shift/centro.py
import simpy
import numpy as np
from collections import defaultdict

from .rng import U_rng, sample_int_or_range_rng
from .utils import hhmm_dias
from .dists import (
    sample_weibull_cajas, sample_chisquared_prep_mixto,
    sample_tiempo_carga_pallet, sample_tiempo_despacho_completo,
    sample_tiempo_chequeo_unitario
)
from .config import PRIO_R1, PRIO_R2PLUS, WEIBULL_CAJAS_PARAMS, CHISQUARED_PREP_MIXTO

class Centro:
    """Motor de procesos de la simulación (Recursos y operaciones)."""
    def __init__(self, env, cfg, pick_gate, rng,
                 total_cajas_facturadas=None, num_camiones_estimado=None):
        self.env, self.cfg, self.pick_gate, self.rng = env, cfg, pick_gate, rng

        # Recursos
        self.pick  = simpy.Resource(env, capacity=cfg["cap_picker"])
        self.grua  = simpy.PriorityResource(env, capacity=cfg["cap_gruero"])
        self.cheq  = simpy.Resource(env, capacity=cfg["cap_chequeador"])
        self.parr  = simpy.Resource(env, capacity=cfg["cap_parrillero"])
        self.movi  = simpy.Resource(env, capacity=cfg["cap_movilizador"])
        self.patio_camiones = simpy.Resource(env, capacity=cfg["cap_patio"])

        # Prioridad de acomodo en V1 (cambia cuando termina PICK V1)
        self.prio_acomodo_v1 = PRIO_R1
        env.process(self._rebalanceo_post_pick_v1())

        # Pausa de almuerzo (salto de reloj)
        self.pausa_almuerzo_activa = False
        self.tiempo_inicio_almuerzo = None
        self.tiempo_fin_almuerzo = None
        env.process(self._manejar_salto_almuerzo())

        # Logs y métricas
        self.eventos = []
        self.grua_ops = []
        self.tiempos_prep_mixto = []
        self.tiempos_chequeo_detallados = []
        self.metricas_chequeadores = {
            "operaciones_totales": 0,
            "tiempo_total_activo": 0,
            "tiempo_total_espera": 0,
            "pallets_chequeados": 0,
            "por_camion": [],
            "por_vuelta": defaultdict(lambda: {
                "operaciones": 0, "tiempo_activo": 0, "tiempo_espera": 0, "pallets": 0
            })
        }

    # ---- Helpers de recursos -------------------------------------------------

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
            ev = self.pick_gate[1]["event"]
        except KeyError:
            return
        yield ev
        self.prio_acomodo_v1 = PRIO_R2PLUS

    # ---- Chequeo por pallet --------------------------------------------------

    def _chequear_pallet_individual(self, vuelta, camion_id, pallet, pallet_idx, total_pallets):
        """Chequea UN pallet y libera el recurso cheq (métricas detalladas)."""
        cfg = self.cfg
        t_request = self.env.now
        with self.cheq.request() as c:
            yield c
            t_espera = self.env.now - t_request
            t_inicio = self.env.now
            t_chk = sample_tiempo_chequeo_unitario(self.rng)
            yield self.env.timeout(t_chk)
            t_fin = self.env.now
            tiene_defecto = self.rng.random() < cfg["p_defecto"]

            self.tiempos_chequeo_detallados.append({
                "vuelta": vuelta, "camion": camion_id, "pallet_id": pallet["id"],
                "pallet_idx": pallet_idx, "total_pallets_camion": total_pallets,
                "es_mixto": pallet.get("mixto", False), "cajas": pallet.get("cajas", 0),
                "tiempo_espera_min": t_espera, "tiempo_chequeo_min": t_chk,
                "tiempo_inicio": t_inicio, "tiempo_fin": t_fin,
                "tiene_defecto": tiene_defecto, "timestamp": hhmm_dias(t_inicio),
            })
            self.metricas_chequeadores["operaciones_totales"] += 1
            self.metricas_chequeadores["tiempo_total_activo"] += t_chk
            self.metricas_chequeadores["tiempo_total_espera"] += t_espera
            self.metricas_chequeadores["pallets_chequeados"] += 1

            vstats = self.metricas_chequeadores["por_vuelta"][vuelta]
            vstats["operaciones"] += 1
            vstats["tiempo_activo"] += t_chk
            vstats["tiempo_espera"] += t_espera
            vstats["pallets"] += 1

        return t_chk, t_espera, tiene_defecto

    # ---- Procesos por vuelta -------------------------------------------------

    def procesa_camion_vuelta(self, vuelta, camion_data):
        """Procesa un camión en una vuelta; PICK ocurre antes del resto."""
        camion_id = camion_data["camion_id"]
        pre_asignados = list(camion_data["pallets"])
        cfg = self.cfg

        # esperar gate de vuelta anterior
        if vuelta > 1:
            yield self.pick_gate[vuelta - 1]["event"]

        t0 = self.env.now

        # A) PICK (solo pallets mixtos)
        pick_list = [p for p in pre_asignados if p["mixto"]]
        if pick_list:
            for idx, pal in enumerate(pick_list):
                with self.pick.request() as r:
                    t_wait_start = self.env.now
                    yield r
                    t_wait = self.env.now - t_wait_start
                    tprep = sample_chisquared_prep_mixto(
                        self.rng, CHISQUARED_PREP_MIXTO["df"], CHISQUARED_PREP_MIXTO["scale"]
                    )
                    self.tiempos_prep_mixto.append({
                        "vuelta": vuelta, "camion": camion_id,
                        "pallet_idx": idx + 1, "tiempo_prep_min": tprep,
                        "tiempo_espera_min": t_wait
                    })
                    yield self.env.timeout(tprep)

        # Señal de fin de PICK (gate por vuelta)
        self.pick_gate[vuelta]["count"] += 1
        if self.pick_gate[vuelta]["count"] >= self.pick_gate[vuelta]["target"]:
            if not self.pick_gate[vuelta]["event"].triggered:
                self.pick_gate[vuelta]["done_time"] = self.env.now
                self.pick_gate[vuelta]["event"].succeed()

        # B) Post-PICK: V1 (paralelo) o staging (secuencial)
        corregidos = fusionados = 0
        if vuelta == 1:
            corregidos, fusionados = yield from self._procesar_vuelta_1_paralelo(vuelta, camion_id, pre_asignados)
        else:
            yield from self._procesar_staging_secuencial(vuelta, camion_id, pre_asignados)

        # Log por camión
        t1 = self.env.now
        cajas_pick_mixto_camion = sum(p["cajas"] for p in pre_asignados if p["mixto"])
        post_cargados = len(pre_asignados) - fusionados if vuelta == 1 else len(pre_asignados)

        evento = {
            "vuelta": vuelta, "camion_id": camion_id,
            "pre_asignados": len(pre_asignados), "post_cargados": post_cargados,
            "fusionados": fusionados, "corregidos": corregidos,
            "cajas_pre": sum(p["cajas"] for p in pre_asignados),
            "cajas_pick_mixto": cajas_pick_mixto_camion,
            "cajas_pickeadas_detalle": {
                "pallets_mixtos": [{"id": p["id"], "cajas": p["cajas"]} for p in pre_asignados if p["mixto"]],
                "pallets_completos": [{"id": p["id"], "cajas": p["cajas"]} for p in pre_asignados if not p["mixto"]],
                "total_cajas_mixtas": cajas_pick_mixto_camion,
                "total_cajas_completas": sum(p["cajas"] for p in pre_asignados if not p["mixto"]),
            },
            "inicio_min": t0, "fin_min": t1,
            "inicio_hhmm": hhmm_dias(cfg["shift_start_min"] + t0),
            "fin_hhmm": hhmm_dias(cfg["shift_start_min"] + t1),
            "tiempo_min": t1 - t0,
            "modo": ("carga" if vuelta == 1 else "staging"),
        }

        if hasattr(self, "_capacidades_usadas"):
            cap = self._capacidades_usadas
            evento.update({
                "capacidad_pallets_disponible": cap["capacidad_pallets_disponible"],
                "capacidad_cajas_disponible": cap["capacidad_cajas_disponible"],
                "utilizacion_pallets_pct": (post_cargados / cap["capacidad_pallets_disponible"] * 100) if cap["capacidad_pallets_disponible"] > 0 else 0,
                "utilizacion_cajas_pct": (sum(p["cajas"] for p in pre_asignados) / cap["capacidad_cajas_disponible"] * 100) if cap["capacidad_cajas_disponible"] > 0 else 0,
                "limitado_por": (
                    "cajas" if cap.get("cajas_asignadas", 0) > cap["capacidad_cajas_disponible"]
                    else ("pallets" if cap.get("pallets_asignados", 0) > cap["capacidad_pallets_disponible"] else "ninguno")
                ),
                "tiempo_chequeo_lognormal_min": cap.get("tiempo_chequeo_total", 0),
                "tasa_chequeo_pallets_por_min": cap.get("tasa_chequeo_promedio", 0),
                "pallets_chequeados": cap.get("pallets_chequeados", 0),
                "tiempo_espera_chequeo_min": cap.get("tiempo_espera_total", 0),
            })
            delattr(self, "_capacidades_usadas")

        self.eventos.append(evento)

    # -- V1: Acomodo + Chequeo en paralelo + Corrección + Fusión + Carga ------

    def _procesar_vuelta_1_paralelo(self, vuelta, camion_id, pallets_asignados):
        cfg = self.cfg
        corregidos = 0
        t_inicio_camion = self.env.now

        with self.patio_camiones.request() as slot:
            yield slot

            # Fase 1: despacho/acomodo + chequeo en paralelo por pallet
            t0 = self.env.now
            procesos = []
            for i, pal in enumerate(pallets_asignados):
                procesos.append(self.env.process(
                    self._procesar_pallet_completo(vuelta, camion_id, pal, i, len(pallets_asignados), i == 0)
                ))
            resultados = yield simpy.AllOf(self.env, procesos)
            info = [r for r in resultados.values()]
            t1 = self.env.now

            tiempos_chk = [x["tiempo_chequeo"] for x in info]
            tiempos_esp = [x["tiempo_espera"] for x in info]
            defectos = [(x["idx"], x["pallet"]) for x in info if x["tiene_defecto"]]

            t_chk_activo = sum(tiempos_chk)
            t_esp_total = sum(tiempos_esp)
            tasa_chk = len(pallets_asignados) / t_chk_activo if t_chk_activo > 0 else 0

            self.metricas_chequeadores["por_camion"].append({
                "vuelta": vuelta, "camion": camion_id,
                "pallets_chequeados": len(pallets_asignados),
                "tiempo_total_fase": (t1 - t0),
                "tiempo_activo": t_chk_activo,
                "tiempo_espera_total": t_esp_total,
                "tiempo_espera_promedio": (np.mean(tiempos_esp) if tiempos_esp else 0),
                "defectos_encontrados": len(defectos),
                "tasa_pallets_por_min": tasa_chk,
                "modo_paralelo": True,
            })

            # Fase 2: correcciones + re-chequeo secuencial de defectuosos
            t2 = self.env.now
            corregidos = len(defectos)
            for idx, pal in defectos:
                dur_corr = U_rng(self.rng, cfg["t_correccion"][0], cfg["t_correccion"][1])
                yield from self._usar_grua(PRIO_R1, dur_corr, "correccion", vuelta, camion_id)
                yield from self._chequear_pallet_individual(vuelta, camion_id, pal, idx + 1, len(pallets_asignados))
            t3 = self.env.now

            # Fase 3: capacidad real, posible fusión de pallets, luego carga
            cap_cajas = sample_weibull_cajas(self.rng, WEIBULL_CAJAS_PARAMS["alpha"], WEIBULL_CAJAS_PARAMS["beta"], WEIBULL_CAJAS_PARAMS["gamma"])
            cap_pallets = sample_int_or_range_rng(self.rng, cfg["capacidad_pallets_camion"])

            pallets_chequeados = pallets_asignados
            cajas_asignadas = sum(p["cajas"] for p in pallets_chequeados)
            fusionados = 0
            if cajas_asignadas > cap_cajas or len(pallets_chequeados) > cap_pallets:
                orden = sorted(pallets_chequeados, key=lambda x: x["cajas"], reverse=True)
                pallets_finales, cajas_cargadas, count = [], 0, 0
                for pal in orden:
                    if cajas_cargadas + pal["cajas"] <= cap_cajas and count < cap_pallets:
                        pallets_finales.append(pal); cajas_cargadas += pal["cajas"]; count += 1
                    else:
                        fusionados += 1
            else:
                pallets_finales = pallets_chequeados

            # Carga (por pallet final)
            for _ in pallets_finales:
                dur = sample_tiempo_carga_pallet(self.rng)
                yield from self._usar_grua(PRIO_R1, dur, "carga", vuelta, camion_id)

            # cierre: parrillero + movilizador
            with self.parr.request() as p:
                yield p; yield self.env.timeout(U_rng(self.rng, cfg["t_ajuste_capacidad"][0], cfg["t_ajuste_capacidad"][1]))
            with self.movi.request() as m:
                yield m; yield self.env.timeout(U_rng(self.rng, cfg["t_mover_camion"][0], cfg["t_mover_camion"][1]))

            # snapshot de capacidades usadas (para métricas/analítica)
            self._capacidades_usadas = {
                "camion": camion_id, "vuelta": vuelta,
                "capacidad_pallets_disponible": cap_pallets,
                "capacidad_cajas_disponible": cap_cajas,
                "pallets_asignados": len(pallets_asignados),
                "cajas_asignadas": sum(p["cajas"] for p in pallets_asignados),
                "pallets_finales": len(pallets_finales),
                "cajas_finales": sum(p["cajas"] for p in pallets_finales),
                "fusionados": fusionados,
                "tiempo_chequeo_total": (t1 - t0),
                "tiempo_chequeo_activo": t_chk_activo,
                "tasa_chequeo_promedio": tasa_chk,
                "pallets_chequeados": len(pallets_asignados),
                "tiempo_espera_chequeo_promedio": (np.mean(tiempos_esp) if tiempos_esp else 0),
                "tiempo_correccion": (t3 - t2),
                "modo_paralelo": True,
            }
        return corregidos, fusionados

    def _procesar_staging_secuencial(self, vuelta, camion_id, pre_asignados):
        cfg = self.cfg
        primera = True
        for pal in pre_asignados:
            if pal["mixto"]:
                dur = U_rng(self.rng, *(cfg["t_acomodo_primera"] if primera else cfg["t_acomodo_otra"]))
                yield from self._usar_grua(PRIO_R2PLUS, dur, "acomodo_v2", vuelta, camion_id)
                primera = False
            else:
                dur = sample_tiempo_despacho_completo(self.rng)
                yield from self._usar_grua(PRIO_R2PLUS, dur, "despacho_completo_v2", vuelta, camion_id)

    # ---- Almuerzo (salto del tiempo simulado) --------------------------------
    def _manejar_salto_almuerzo(self):
        cfg = self.cfg
        t_ini = cfg.get("almuerzo_inicio_min", 120)
        t_salto = cfg.get("almuerzo_salto_min", 150)
        yield self.env.timeout(t_ini)
        self.pausa_almuerzo_activa = True
        self.tiempo_inicio_almuerzo = self.env.now
        yield self.env.timeout(t_salto - self.env.now)
        self.pausa_almuerzo_activa = False
        self.tiempo_fin_almuerzo = self.env.now

    # ---- Paso por pallet (despacho/acomodo y chequeo) ------------------------
    def _procesar_pallet_completo(self, vuelta, camion_id, pallet, idx, total, es_primero):
        if not pallet["mixto"]:
            dur_dc = sample_tiempo_despacho_completo(self.rng)
            yield from self._usar_grua(PRIO_R1, dur_dc, "despacho_completo", vuelta, camion_id)

        t_acomodo = self.cfg["t_acomodo_primera"] if es_primero else self.cfg["t_acomodo_otra"]
        dur_a = U_rng(self.rng, t_acomodo[0], t_acomodo[1])
        yield from self._usar_grua(self.prio_acomodo_v1, dur_a, "acomodo_v1", vuelta, camion_id)

        t_chk, t_esp, defect = yield from self._chequear_pallet_individual(vuelta, camion_id, pallet, idx + 1, total)
        return {"idx": idx, "pallet": pallet, "tiempo_chequeo": t_chk, "tiempo_espera": t_esp, "tiene_defecto": defect}
