import simpy
from collections import defaultdict

from ..night.rng import make_rng, U_rng
from ..night.utils import hhmm_dias
from ..night.dists import (
    sample_tiempo_chequeo_unitario,
    sample_tiempo_carga_pallet,
)
from .config import get_day_config
from ..night.metrics import calcular_ocupacion_recursos

from .utils import (
    calcular_tiempo_retorno,
    formatear_cronograma_dia,
)

def _fmt(mins):
    """Formato compacto 'Hh Mm Ss' o 'Mm Ss'."""
    try:
        mins = float(mins)
    except Exception:
        return str(mins)
    h = int(mins // 60)
    m = int(mins % 60)
    s = int(round((mins - int(mins)) * 60))
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{mins:.2f} min"


class CentroDia:
    """Chequeo + carga de pallets para vueltas >= 2, con dotación de día."""
    def __init__(self, env, cfg):
        self.env, self.cfg = env, cfg

        # Recursos
        self.grua  = simpy.PriorityResource(env, capacity=cfg.get("cap_gruero", 4))
        self.cheq  = simpy.Resource(env, capacity=cfg.get("cap_chequeador", 2))
        self.parr  = simpy.Resource(env, capacity=cfg.get("cap_parrillero", 1))
        self.movi  = simpy.Resource(env, capacity=cfg.get("cap_movilizador", 1))
        self.patio_camiones = simpy.Resource(env, capacity=cfg.get("cap_patio", 10))

        # Cola global de pallets para chequeo anticipado (desde minuto 0)
        self.queue_chequeo = simpy.Store(env)

        # Logs y métricas
        self.eventos = []
        self.grua_ops = []
        self.metricas_chequeadores = {
            "operaciones_totales": 0,
            "tiempo_total_activo": 0,
            "tiempo_total_espera": 0,
            "pallets_chequeados": 0,
            "por_camion": [],
            "por_vuelta": defaultdict(lambda: {
                "operaciones": 0, "tiempo_activo": 0, "tiempo_espera": 0, "pallets": 0
            }),
        }
        self.metricas_recursos = {
            "pickers": {"tiempo_activo": 0, "operaciones": 0},
            "chequeadores": {"tiempo_activo": 0, "operaciones": 0},
            "grueros": {"tiempo_activo": 0, "operaciones": 0},
            "parrilleros": {"tiempo_activo": 0, "operaciones": 0},
            "movilizadores": {"tiempo_activo": 0, "operaciones": 0},
        }
        self.linea_tiempo = []

    # ------------------------------- Chequeo global ---------------------------
    def _worker_chequeo_global(self, wid: int):
        """
        Toma pallets de self.queue_chequeo y los chequea
        independientemente de la presencia del camión en patio.
        """
        while True:
            pallet, camion_id, vuelta, idx, total = yield self.queue_chequeo.get()

            t_request = self.env.now
            with self.cheq.request() as c:
                yield c
                t_espera = self.env.now - t_request
                t_chk = sample_tiempo_chequeo_unitario(rng=self.rng)
                yield self.env.timeout(t_chk)

                # métricas chequeadores
                self.metricas_chequeadores["operaciones_totales"] += 1
                self.metricas_chequeadores["tiempo_total_activo"] += t_chk
                self.metricas_chequeadores["tiempo_total_espera"] += t_espera
                self.metricas_chequeadores["pallets_chequeados"] += 1
                vstats = self.metricas_chequeadores["por_vuelta"][vuelta]
                vstats["operaciones"] += 1
                vstats["tiempo_activo"] += t_chk
                vstats["tiempo_espera"] += t_espera
                vstats["pallets"] += 1

            # marcar pallet como chequeado y liberar al camión que espera
            pallet["_chequed"] = True
            evt = pallet.get("_evt_chk")
            if evt is not None and not evt.triggered:
                evt.succeed()

    def _esperar_chequeo_lote(self, pallets, camion_id, vuelta):
        pendientes = [p for p in pallets if not p.get("_chequed", False)]
        if pendientes:
            self._dbg("⌛ Esperando chequeo de pallets antes de cargar",
                      camion=camion_id, pendientes=len(pendientes), vuelta=vuelta)
            eventos = [p["_evt_chk"] for p in pendientes]
            yield simpy.events.AllOf(self.env, eventos)

    # ------------------------------- Depuración -------------------------------
    def _dbg(self, msg, **meta):
        if not self.cfg.get("debug", False):
            return
        t = self.env.now
        hhmm = hhmm_dias(self.cfg.get("shift_start_min", 0) + t)
        base = f"[{t:7.2f} min | {hhmm}] {msg}"
        if meta:
            extras = " | " + " ".join(f"{k}={v}" for k, v in meta.items())
        else:
            extras = ""
        print(base + extras)

    # ----------------------- Utilidades internas de registro ------------------
    def _registrar(self, descripcion, tipo="general", meta=None):
        t = self.env.now
        self.linea_tiempo.append({
            "tiempo_min": t,
            "hora": hhmm_dias(self.cfg.get("shift_start_min", 0) + t),
            "descripcion": descripcion,
            "tipo": tipo,
            "metadata": meta or {},
        })
        self._dbg(f"📝 {tipo.upper()}: {descripcion}", **(meta or {}))

    def _usar_grua(self, dur, label, vuelta, camion_id):
        t_req = self.env.now
        with self.grua.request(priority=0) as g:
            yield g
            wait = self.env.now - t_req
            t_start = self.env.now
            yield self.env.timeout(dur)
            t_end = self.env.now

        # métricas grúa
        self.metricas_recursos["grueros"]["tiempo_activo"] += dur
        self.metricas_recursos["grueros"]["operaciones"] += 1
        self.grua_ops.append({
            "vuelta": vuelta, "camion": camion_id, "label": label,
            "wait": wait, "hold": dur, "start": t_start, "end": t_end
        })

    # ----------------------------- Proceso por vuelta -------------------------
    def procesar_vuelta(self, camion_id, pallets, vuelta: int):
        cfg = self.cfg

        # (1) Asegurar que todos los pallets están chequeados
        yield from self._esperar_chequeo_lote(pallets, camion_id, vuelta)

        # (2) Tomar patio y ejecutar carga + cierre + movilización y salida
        with self.patio_camiones.request() as slot:
            yield slot
            t0 = self.env.now
            self._registrar(
                f"Camión {camion_id} inicia proceso v{vuelta}",
                "inicio_camion", {"camion": camion_id, "vuelta": vuelta}
            )

            # Carga por pallet (día)
            for _ in pallets:
                dur = sample_tiempo_carga_pallet(rng=self.rng)
                yield from self._usar_grua(dur, "carga_dia", vuelta, camion_id)

            # Cierre: parrillero
            with self.parr.request() as p:
                yield p
                t_parr = U_rng(self.rng, *cfg.get("t_ajuste_capacidad", (1.5, 3.0)))
                yield self.env.timeout(t_parr)
                self.metricas_recursos["parrilleros"]["tiempo_activo"] += t_parr
                self.metricas_recursos["parrilleros"]["operaciones"] += 1

            # Movilización y salida a ruta (control explícito de salida)
            with self.movi.request() as m:
                yield m
                t_movi = U_rng(self.rng, *cfg.get("t_mover_camion", (1.3, 1.4)))
                yield self.env.timeout(t_movi)
                self.metricas_recursos["movilizadores"]["tiempo_activo"] += t_movi
                self.metricas_recursos["movilizadores"]["operaciones"] += 1

            t1 = self.env.now
            # Evento operativo (camión en patio)
            self.eventos.append({
                "vuelta": vuelta,
                "camion_id": camion_id,
                "pre_asignados": len(pallets),
                "post_cargados": len(pallets),
                "num_pallets": len(pallets),
                "fusionados": 0,
                "corregidos": 0,
                "cajas_pre": sum(p.get("cajas", 0) for p in pallets),
                "cajas_pick_mixto": sum(p.get("cajas", 0) for p in pallets if p.get("mixto", False)),
                "cajas_pickeadas_detalle": {
                    "pallets_mixtos": [p for p in pallets if p.get("mixto", False)],
                    "pallets_completos": [p for p in pallets if not p.get("mixto", False)],
                    "total_cajas_mixtas": sum(p.get("cajas", 0) for p in pallets if p.get("mixto", False)),
                    "total_cajas_completas": sum(p.get("cajas", 0) for p in pallets if not p.get("mixto", False)),
                },
                "inicio_min": t0, "fin_min": t1,
                "inicio_hhmm": hhmm_dias(cfg.get("shift_start_min", 0) + t0),
                "fin_hhmm": hhmm_dias(cfg.get("shift_start_min", 0) + t1),
                "tiempo_min": t1 - t0,
                "modo": "carga_dia",
            })
            self._registrar(
                f"Camión {camion_id} sale nuevamente a ruta (v{vuelta})",
                "fin_camion", {"camion": camion_id, "vuelta": vuelta, "duracion": _fmt(t1 - t0)}
            )
            return t1  # fin dentro de patio

    # --------------------------------- Driver --------------------------------
    def run(self, asignaciones, seed=None, estado_inicial_dia=None):
        """
        asignaciones: lista de dicts:
          [{"camion_id": str, "pallets": [...], "offset_idx": i, "vuelta": int>=2}, ...]
        Puede contener múltiples lotes por el mismo camión para vueltas 2, 3, 4, ...

        estado_inicial_dia: dict opcional para detectar camiones que
        quedaron cargados en V1 pero sin salida nocturna y despacharlos al inicio del día.
        """
        self.rng = make_rng(seed)
        salidas = []
        retornos = []
        salidas_v1_pendientes = []

        # --- 0) Detectar camiones V1 pendientes de salida (desde la noche)
        pendientes_v1 = set()
        if isinstance(estado_inicial_dia, dict):
            for c in estado_inicial_dia.get("camiones_en_ruta", []) or []:
                # Consideramos "pendiente" si no hubo hora_estimada_regreso (no se registró salida real).
                if not c.get("hora_estimada_regreso"):
                    cid = c.get("camion_id")
                    if cid:
                        pendientes_v1.add(cid)

        # Debug de asignaciones
        if self.cfg.get("debug", False):
            print("\n=== 📦 ASIGNACIONES DÍA (entrada) ===")
            for a in asignaciones:
                cajas = sum(p.get("cajas", 0) for p in a["pallets"])
                print(f" - Camión {a['camion_id']}: pallets={len(a['pallets'])} "
                      f"cajas={cajas} vuelta={a.get('vuelta', 2)}")
            if pendientes_v1:
                print(f"=== 🚚 V1 pendientes de salida (día): {sorted(pendientes_v1)} ===")

        # 1) Inicializar chequeo global (todos los pallets desde el minuto 0)
        for a in asignaciones:
            total = len(a["pallets"])
            for idx, p in enumerate(a["pallets"], start=1):
                p["_chequed"] = False
                p["_evt_chk"] = self.env.event()
                # encolar pallet al chequeo global
                self.queue_chequeo.put((p, a["camion_id"], a.get("vuelta", 2), idx, total))

        for wid in range(self.cfg.get("cap_chequeador", 2)):
            self.env.process(self._worker_chequeo_global(wid))

        # 2) Agrupar lotes por camión y ordenarlos por 'vuelta'
        itinerarios = defaultdict(list)
        offset_por_camion = {}
        for a in asignaciones:
            itinerarios[a["camion_id"]].append({
                "vuelta": int(max(2, a.get("vuelta", 2))),
                "pallets": a["pallets"],
            })
            # conservar offset del primer visto
            offset_por_camion.setdefault(a["camion_id"], int(a.get("offset_idx", 0)))

        for cid in itinerarios.keys():
            itinerarios[cid].sort(key=lambda L: L["vuelta"])

        # 2.1) Procesos para despachar V1 pendientes (consumen movi + patio)
        evt_salio_v1 = {}
        def _proc_despachar_v1(cid: str):
            # ocupa patio y movilizador para sacar el camión
            with self.patio_camiones.request() as slot:
                yield slot
                with self.movi.request() as m:
                    yield m
                    t_m = U_rng(self.rng, *self.cfg.get("t_mover_camion", (1.3, 1.4)))
                    yield self.env.timeout(t_m)
                    self.metricas_recursos["movilizadores"]["tiempo_activo"] += t_m
                    self.metricas_recursos["movilizadores"]["operaciones"] += 1
            ts = self.env.now
            salidas_v1_pendientes.append({
                "camion_id": cid,
                "vuelta": 1,
                "hora_salida": hhmm_dias(self.cfg.get("shift_start_min", 0) + ts)
            })
            ev = evt_salio_v1.get(cid)
            if ev and not ev.triggered:
                ev.succeed()

        for cid in pendientes_v1:
            evt_salio_v1[cid] = self.env.event()
            self.env.process(_proc_despachar_v1(cid))

        # 3) Proceso por camión que itera sus vueltas (>=2)
        def camion_runner(camion_id, lotes, offset_idx):
            # Llegada inicial para la PRIMERA vuelta (>=2)
            base_travel_min = calcular_tiempo_retorno(offset_idx, self.cfg, self.rng)

            if camion_id in evt_salio_v1:
                # Espera a que el camión efectivamente salga en V1 dentro del día
                yield evt_salio_v1[camion_id]
                arrive_min = base_travel_min
            else:
                arrive_min = base_travel_min

            arrive_hhmm = hhmm_dias(self.cfg.get("shift_start_min", 0) + self.env.now + arrive_min)
            self._dbg(f"🛣️ EN RUTA V{lotes[0]['vuelta']}: ETA llegada",
                      camion=camion_id, eta_min=f"{arrive_min:.2f}", eta_hhmm=arrive_hhmm)
            yield self.env.timeout(max(0.0, arrive_min))
            self._dbg(f"⬅️  LLEGA camión V{lotes[0]['vuelta']}", camion=camion_id)

            # Iterar todas las vueltas asignadas al camión
            for i, lote in enumerate(lotes):
                v = lote["vuelta"]
                pallets = lote["pallets"]

                # Procesar dentro del CD
                t_fin = (yield self.env.process(self.procesar_vuelta(camion_id, pallets, vuelta=v)))
                salidas.append({
                    "camion_id": camion_id,
                    "vuelta": v,
                    "hora_salida": hhmm_dias(self.cfg.get("shift_start_min", 0) + t_fin)
                })

                # Viaje y retorno al CD (deja listo para la siguiente vuelta si existe)
                ret_min = calcular_tiempo_retorno(offset_idx, self.cfg, self.rng)
                ret_eta_hhmm = hhmm_dias(self.cfg.get("shift_start_min", 0) + self.env.now + ret_min)
                self._dbg("🛣️  RETORNA: ETA retorno",
                          camion=camion_id, vuelta=v, eta_min=f"{ret_min:.2f}", eta_hhmm=ret_eta_hhmm)
                yield self.env.timeout(max(0.0, ret_min))

                self._registrar(
                    f"camion {camion_id} retorna tras vuelta {v}",
                    "retorno_camion", {"camion": camion_id, "vuelta": v}
                )
                retornos.append({
                    "camion_id": camion_id,
                    "vuelta": v,
                    "hora_retorno": hhmm_dias(self.cfg.get("shift_start_min", 0) + self.env.now)
                })

                # Si hay otra vuelta, considerar esta llegada como el "arribo" de la siguiente
                if i + 1 < len(lotes):
                    next_v = lotes[i + 1]["vuelta"]
                    self._dbg(f"⬅️  LLEGA camión V{next_v}", camion=camion_id)

        # Lanzar un proceso por camión (no por lote) para soportar v>=3
        for cid, lotes in itinerarios.items():
            self.env.process(camion_runner(cid, lotes, offset_por_camion.get(cid, 0)))

        # Correr hasta el fin del día (no se usa buffer externo)
        self.env.run(until=self.cfg.get("shift_end_min", 1440))

        # Cierre y métricas
        total_linea = max((e["tiempo_min"] for e in self.linea_tiempo), default=0)
        total_fin = max(max((e["fin_min"] for e in self.eventos), default=0), total_linea)

        ocupacion = calcular_ocupacion_recursos(
            self, self.cfg,
            tiempo_total_turno=max(total_fin, self.cfg.get("shift_end_min", 480))
        )

        # Resumen final (debug)
        if self.cfg.get("debug", False):
            print("\n=== 📊 RESUMEN DÍA ===")
            print(f"Camiones procesados (eventos en patio): {len(self.eventos)}")
            print(f"Salidas registradas (v>=2): {len(salidas)}")
            print(f"Salidas V1 pendientes despachadas: {len(salidas_v1_pendientes)}")
            print("Ocupación recursos:")
            for k, v in ocupacion.items():
                pct = v.get("porcentaje_ocupacion", 0)
                t_act = v.get("tiempo_activo", 0)
                ops  = v.get("operaciones", 0)
                print(f" - {k:14s} -> {pct:5.1f}%  activo={_fmt(t_act)}  ops={ops}")
            print("=====================================\n")

        return {
            "salidas_v1_pendientes": salidas_v1_pendientes,
            "nueva_salida_camiones": salidas,   # v>=2
            "retornos_camiones": retornos,
            "centro_eventos": self.eventos,
            "grua_operaciones": self.grua_ops,
            "ocupacion_recursos": ocupacion,
            "timeline": self.linea_tiempo,
            "turno_fin_real": hhmm_dias(self.cfg.get("shift_start_min", 0) + total_fin),
            "cronograma_dia": formatear_cronograma_dia(self.eventos),
        }


# -------------------------------- Helpers de armado ---------------------------
def construir_asignaciones_desde_estado(estado_inicial_dia):
    """
    Arma la cola de trabajo del día. Si 'camiones_en_ruta' está vacío,
    cae por defecto a los camiones detectados en 'pallets_listos_para_carga'.
    """
    from collections import defaultdict

    asignaciones = []
    pallets_por_camion = defaultdict(list)

    # 1) Indexar pallets listos (pueden venir varias vueltas por camión)
    for p in estado_inicial_dia.get("pallets_listos_para_carga", []) or []:
        cid = p.get("camion_asignado") or p.get("camion") or p.get("camion_id")
        v   = int(max(2, p.get("vuelta_origen", 2)))
        pallets = (p.get("pallets_mixtos") or []) + (p.get("pallets_completos") or [])
        if cid and pallets:
            pallets_por_camion[cid].append({"vuelta": v, "pallets": pallets})

    # 2) Orden base: lo que venga en 'camiones_en_ruta' (si existe)
    cam_en_ruta = [c.get("camion_id") for c in (estado_inicial_dia.get("camiones_en_ruta") or []) if c.get("camion_id")]

    # 2.a) Si está vacío, caer al set de camiones detectados en pallets_listos
    if not cam_en_ruta:
        camiones = sorted(pallets_por_camion.keys())
    else:
        # Asegurar que no se pierda ningún camión con pallets listos
        camiones = cam_en_ruta + [cid for cid in pallets_por_camion.keys() if cid not in cam_en_ruta]

    # 3) Construir asignaciones (todas las vueltas por camión, ordenadas)
    for i, cid in enumerate(camiones):
        lotes = sorted(pallets_por_camion.get(cid, []), key=lambda x: x["vuelta"])
        for lote in lotes:
            asignaciones.append({
                "camion_id": cid,
                "pallets":   lote["pallets"],
                "vuelta":    lote["vuelta"],
                "offset_idx": i,   # para la ETA inicial / retorno
            })

    return asignaciones


# ------------------------------ Preview pre-turno -----------------------------
def _resumen_pre_turno(asignaciones):
    """
    Devuelve un resumen por vuelta con el detalle de camiones/pallets/cajas.
    """
    por_vuelta = defaultdict(list)
    for a in asignaciones:
        cajas = sum(p.get("cajas", 0) for p in a["pallets"])
        por_vuelta[a.get("vuelta", 2)].append({
            "camion_id": a["camion_id"],
            "pallets": len(a["pallets"]),
            "cajas": cajas,
        })
    resumen = []
    for v, lst in sorted(por_vuelta.items()):
        total_pallets = sum(x["pallets"] for x in lst)
        total_cajas = sum(x["cajas"] for x in lst)
        resumen.append({
            "vuelta": v,
            "total_camiones": len(lst),
            "total_pallets": total_pallets,
            "total_cajas": total_cajas,
            "detalle": sorted(lst, key=lambda x: x["camion_id"]),
        })
    return resumen

def imprimir_resumen_pre_turno(resumen):
    for r in resumen:
        print(f"\n🔁 Vuelta {r['vuelta']} — camiones={r['total_camiones']} | "
              f"pallets={r['total_pallets']} | cajas={r['total_cajas']}")
        for d in r["detalle"]:
            print(f"  · {d['camion_id']:>6}  pallets={d['pallets']:>2}  cajas={d['cajas']}")

def preview_turno_dia(estado_inicial_dia, seed=None):
    """
    Solo arma asignaciones y devuelve un resumen pre-turno (no corre SimPy).
    """
    cfg = get_day_config()
    rng = make_rng(seed)  # por consistencia, aunque aquí no muestreamos tiempos
    asignaciones = construir_asignaciones_desde_estado(estado_inicial_dia)
    resumen = _resumen_pre_turno(asignaciones)
    return {"cfg_dia": cfg, "asignaciones": asignaciones, "pre_turno": resumen}


# ------------------------------ API principal ---------------------------------
def simular_turno_dia(estado_inicial_dia, seed=None):
    """Simula el turno día dado el estado de salida del turno noche."""
    cfg = get_day_config()  # única fuente de configuración
    env = simpy.Environment()
    centro = CentroDia(env, cfg)

    # Construcción de asignaciones (pueden incluir v=2,3,4,...)
    asignaciones = construir_asignaciones_desde_estado(estado_inicial_dia)

    # Print previo (debug) para ver cómo llega el estado de la noche
    if cfg.get("debug", False):
        print("\n=== 🌙→☀️ ESTADO INICIAL DÍA (desde NOCHE) ===")
        print(f"Camiones en ruta (fin noche): {len(estado_inicial_dia.get('camiones_en_ruta', []))}")
        print(f"Lotes listos para carga: {len(estado_inicial_dia.get('pallets_listos_para_carga', []))}")
        print(f"Asignaciones construidas: {len(asignaciones)}")
        print("=============================================\n")

    # (Opcional) Preview antes de correr
    resumen_pre = _resumen_pre_turno(asignaciones)
    imprimir_resumen_pre_turno(resumen_pre)

    # Pasamos el estado para poder despachar V1 pendientes dentro del run()
    resultado = centro.run(asignaciones, seed=seed, estado_inicial_dia=estado_inicial_dia)

    resultado.update({
        "asignaciones_entrada": asignaciones,
        "turno_inicio": hhmm_dias(cfg.get("shift_start_min", 0)),
        "turno_fin_nominal": hhmm_dias(cfg.get("shift_end_min", 480)),
        # "pre_turno": resumen_pre,  # descomenta si lo quieres en la salida
    })
    return resultado
