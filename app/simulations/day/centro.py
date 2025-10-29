# app/simulations/day/centro.py
import simpy
from collections import defaultdict
from .rng import make_rng, U_rng
from .utils import hhmm_dias
from .dists import (
    sample_tiempo_chequeo_unitario,
    sample_tiempo_carga_pallet,
    sample_lognormal_retorno_camion,
    sample_delta_hito0_1, sample_delta_hito1_2, sample_delta_hito2_3,
)
from .metrics import calcular_ocupacion_recursos
from .utils import formatear_cronograma_dia, sample_num_camiones_t1_dia

def _fmt(mins):
    try: mins = float(mins)
    except Exception: return str(mins)
    h = int(mins // 60); m = int(mins % 60); s = int(round((mins - int(mins)) * 60))
    if h > 0: return f"{h}h {m:02d}m {s:02d}s"
    if m > 0: return f"{m}m {s:02d}s"
    return f"{mins:.2f} min"

class CentroDia:
    """Chequeo + carga de pallets para vueltas >=2 y flujo T1 por hitos."""
    def __init__(self, env, cfg):
        self.env, self.cfg = env, cfg

        # Recursos
        self.grua  = simpy.PriorityResource(env, capacity=cfg.get("cap_gruero", 4))
        self.cheq  = simpy.Resource(env, capacity=cfg.get("cap_chequeador", 2))
        self.parr  = simpy.Resource(env, capacity=cfg.get("cap_parrillero", 1))
        self.movi  = simpy.Resource(env, capacity=cfg.get("cap_movilizador", 1))
        self.patio_camiones = simpy.Resource(env, capacity=cfg.get("cap_patio", 10))
        self.porteria = simpy.Resource(env, capacity=cfg.get("cap_porteria", 1))

        # --- Patio equivalente (T2=1, T1=2) ---
        self.patio_eq_cap = cfg.get("patio_eq_cap", 4)
        self.patio_equivalentes = simpy.Container(self.env, init=self.patio_eq_cap, capacity=self.patio_eq_cap)
        self.patio_eq_trace = []  # (op, t, k, quien, level_restante)

        # Chequeo global
        self.queue_chequeo = simpy.Store(env)

        # Logs/Métricas
        self.eventos = []
        self.grua_ops = []
        self.cheq_ops = []
        self.parr_ops = []
        self.movi_ops = []
        self.port_ops = []
        self.pick_ops = []

        self.t1_eventos = []
        self.t1_contador = 0
        self.metricas_chequeadores = {
            "operaciones_totales": 0, "tiempo_total_activo": 0, "tiempo_total_espera": 0, "pallets_chequeados": 0,
            "por_camion": [],
            "por_vuelta": defaultdict(lambda: {"operaciones": 0, "tiempo_activo": 0, "tiempo_espera": 0, "pallets": 0}),
        }
        self.metricas_recursos = {
            "pickers": {"tiempo_activo": 0, "operaciones": 0},
            "chequeadores": {"tiempo_activo": 0, "operaciones": 0},
            "grueros": {"tiempo_activo": 0, "operaciones": 0},
            "parrilleros": {"tiempo_activo": 0, "operaciones": 0},
            "movilizadores": {"tiempo_activo": 0, "operaciones": 0},
            "porteros": {"tiempo_activo": 0, "operaciones": 0},
        }
        self.linea_tiempo = []

    def _abs_min(self, hhmm_or_int):
        """Convierte 'HH:MM' o int a minutos absolutos [0..1440)."""
        if isinstance(hhmm_or_int, (int, float)):
            return int(hhmm_or_int)
        h, m = map(int, str(hhmm_or_int).split(":"))
        return h * 60 + m

    def _aplicar_capacidades(self, caps: dict):
        """Actualiza la dotación (capacity) de recursos según 'caps'."""
        if "grua" in caps:        self.grua._capacity = int(caps["grua"])
        if "chequeador" in caps:  self.cheq._capacity = int(caps["chequeador"])
        if "parrillero" in caps:  self.parr._capacity = int(caps["parrillero"])
        if "movilizador" in caps: self.movi._capacity = int(caps["movilizador"])
        if "porteria" in caps:    self.porteria._capacity = int(caps["porteria"])

        # Debug del cambio
        self._dbg("🔁 Cambio de turno aplicado",
                grua=self.grua._capacity,
                chequeador=self.cheq._capacity,
                parrillero=self.parr._capacity,
                movilizador=self.movi._capacity,
                porteria=self.porteria._capacity)


    # ---- Helpers patio equivalente (con DEBUG) ----
    def _patio_eq_get(self, k: int, quien: str):
        """
        Reserva k equivalentes (bloquea si no hay). Emite debug con:
        - cupos libres antes del pedido
        - tiempo de espera hasta entrar
        - cupos libres y ocupación al entrar
        """
        cap = self.patio_eq_cap
        libres_antes = self.patio_equivalentes.level
        self._dbg("⏳ Solicita patio", quien=quien, solicitados=k, libres=f"{libres_antes}/{cap}")

        t0 = self.env.now
        # Bloquea hasta tener cupos suficientes
        yield self.patio_equivalentes.get(k)
        wait = self.env.now - t0

        libres_despues = self.patio_equivalentes.level       # cupos libres restantes
        ocupacion = self.patio_eq_cap - libres_despues       # equivalentes en uso

        # Traza + debug
        self.patio_eq_trace.append(("GET", self.env.now, k, quien, libres_despues))
        self._dbg("🚪 ENTRA a patio", quien=quien, equivalentes=k,
                espera_min=round(wait, 2),
                libres=f"{libres_despues}/{cap}",
                ocupacion_eq=ocupacion)

    def _gestor_turnos(self):
        """
        Aplica cambios de capacidad en los hitos de inicio de turno.
        Lee cfg['shifts_day'] con 'start'/'end' y 'caps'.
        """
        shifts = list(self.cfg.get("shifts_day") or [])
        if not shifts:
            return

        base_abs = self.cfg.get("shift_start_min", 0)

        # Ordenar por hora de inicio
        sched = []
        for sh in shifts:
            t_start_abs = self._abs_min(sh.get("start", base_abs))
            caps = sh.get("caps", {})
            sched.append((t_start_abs, caps))
        sched.sort(key=lambda x: x[0])

        # Aplicar inmediatamente el primer turno si coincide con el inicio del día
        if sched and sched[0][0] == base_abs:
            self._aplicar_capacidades(sched[0][1])

        # Recorrer cambios (incluye el de las 16:00)
        for t_abs, caps in sched:
            t_rel = max(0, t_abs - base_abs)
            if t_rel > self.env.now:
                yield self.env.timeout(t_rel - self.env.now)
            self._registrar("Cambio de turno", "turno", {
                "desde": f"{t_abs//60:02d}:{t_abs%60:02d}", "caps": caps
            })
            self._aplicar_capacidades(caps)

    def _patio_eq_put(self, k: int, quien: str):
        """
        Libera k equivalentes (no bloquea). Emite debug con:
        - cupos libres luego de liberar
        - ocupación resultante
        """
        self.patio_equivalentes.put(k)
        libres = self.patio_equivalentes.level
        ocupacion = self.patio_eq_cap - libres

        # Traza + debug
        self.patio_eq_trace.append(("PUT", self.env.now, k, quien, libres))
        self._dbg("🏁 SALE de patio", quien=quien, equivalentes=k,
                libres=f"{libres}/{self.patio_eq_cap}",
                ocupacion_eq=ocupacion)

    def resumen_patio_equivalentes(self):
        if not self.patio_eq_trace:
            return {"timeline": [], "violaciones": []}
        ev = []
        for op, t, k, quien, level in self.patio_eq_trace:
            delta = +k if op == "GET" else -k
            ev.append((t, delta, op, quien))
        ev.sort(key=lambda x: x[0])
        timeline, usados = [], 0
        t_last = ev[0][0]
        for t, delta, *_ in ev:
            if t > t_last:
                timeline.append((t_last, t, usados))
                t_last = t
            usados += delta
        viol = [(ini, fin, u) for (ini, fin, u) in timeline if u > self.patio_eq_cap]
        return {"timeline": timeline, "violaciones": viol}

    # ----------------------------- Chequeo global ------------------------------
    def _worker_chequeo_global(self, wid: int):
        while True:
            pallet, camion_id, vuelta, idx, total = yield self.queue_chequeo.get()
            t_request = self.env.now
            with self.cheq.request() as c:
                yield c
                t_espera = self.env.now - t_request
                t_chk = sample_tiempo_chequeo_unitario(rng=self.rng)
                yield self.env.timeout(t_chk)
                self.metricas_chequeadores["operaciones_totales"] += 1
                self.metricas_chequeadores["tiempo_total_activo"] += t_chk
                self.metricas_chequeadores["tiempo_total_espera"] += t_espera
                self.metricas_chequeadores["pallets_chequeados"] += 1
                vstats = self.metricas_chequeadores["por_vuelta"][vuelta]
                vstats["operaciones"] += 1
                vstats["tiempo_activo"] += t_chk
                vstats["tiempo_espera"] += t_espera
                vstats["pallets"] += 1
            pallet["_chequed"] = True
            evt = pallet.get("_evt_chk")
            if evt is not None and not evt.triggered:
                evt.succeed()

    def _esperar_chequeo_lote(self, pallets, camion_id, vuelta):
        pendientes = [p for p in pallets if not p.get("_chequed", False)]
        if pendientes:
            #self._dbg("⌛ Esperando chequeo de pallets antes de cargar",
            #          camion=camion_id, pendientes=len(pendientes), vuelta=vuelta)
            eventos = [p["_evt_chk"] for p in pendientes]
            yield simpy.events.AllOf(self.env, eventos)

    # ------------------------------- Depuración --------------------------------
    def _dbg(self, msg, **meta):
        if not self.cfg.get("debug", False):
            return
        t = self.env.now
        hhmm = hhmm_dias(self.cfg.get("shift_start_min", 0) + t)
        base = f"[{t:7.2f} min | {hhmm}] {msg}"
        extras = " | " + " ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
        print(base + extras)

    # ----------------------- Utilidades internas de registro -------------------
    def _registrar(self, descripcion, tipo="general", meta=None):
        t = self.env.now
        self.linea_tiempo.append({
            "tiempo_min": t, "hora": hhmm_dias(self.cfg.get("shift_start_min", 0) + t),
            "descripcion": descripcion, "tipo": tipo, "metadata": meta or {},
        })
        #self._dbg(f"📝 {tipo.upper()}: {descripcion}", **(meta or {}))

    def _usar_grua(self, dur, label, vuelta, camion_id):
        t_req = self.env.now
        with self.grua.request(priority=0) as g:
            yield g
            wait = self.env.now - t_req
            t_start = self.env.now
            yield self.env.timeout(dur)
            t_end = self.env.now
        self.metricas_recursos["grueros"]["tiempo_activo"] += dur
        self.metricas_recursos["grueros"]["operaciones"] += 1
        self.grua_ops.append({
            "vuelta": vuelta, "camion": camion_id, "label": label,
            "wait": wait, "hold": dur, "start": t_start, "end": t_end
        })

    # ----------------------------- Proceso por vuelta (v>=2) -------------------
    def procesar_vuelta(self, camion_id, pallets, vuelta: int):
        cfg = self.cfg
        yield from self._esperar_chequeo_lote(pallets, camion_id, vuelta)

        # >>> Reserva patio equivalente (T2=1) desde entrada a patio hasta el FINAL <<<
        yield from self._patio_eq_get(1, f"T2 {camion_id} v{vuelta}")
        try:
            with self.patio_camiones.request() as slot:
                yield slot
                t0 = self.env.now
                self._registrar(
                    f"Camión {camion_id} inicia proceso v{vuelta}",
                    "inicio_camion", {"camion": camion_id, "vuelta": vuelta}
                )
                for _ in pallets:
                    dur = sample_tiempo_carga_pallet(rng=self.rng)
                    yield from self._usar_grua(dur, "carga_dia", vuelta, camion_id)

                with self.parr.request() as p:
                    yield p
                    t_parr = U_rng(self.rng, *cfg.get("t_ajuste_capacidad", (1.5, 3.0)))
                    t_parr_start = self.env.now
                    yield self.env.timeout(t_parr)
                    t_parr_end = self.env.now
                    self.metricas_recursos["parrilleros"]["tiempo_activo"] += t_parr
                    self.parr_ops.append({"start": t_parr_start, "end": t_parr_end, "hold": t_parr})
                    self.metricas_recursos["parrilleros"]["operaciones"] += 1

                t1 = self.env.now
                self.eventos.append({
                    "vuelta": vuelta, "camion_id": camion_id,
                    "pre_asignados": len(pallets), "post_cargados": len(pallets),
                    "num_pallets": len(pallets), "fusionados": 0, "corregidos": 0,
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
                return t1
        finally:
            # NO yield en finally
            self._patio_eq_put(1, f"T2 {camion_id} v{vuelta}")

    # ----------------------------- Flujo T1 por hitos --------------------------
    def _proceso_camion_T1(self, camion_id: str):
        cfg = self.cfg
        t_inicia = self.env.now
        self._registrar(f"Arribo {camion_id} a portería (H0)", "t1_hito", {"camion": camion_id, "hito": 0})

        # H0→H1: Portería (entrada)
        with self.porteria.request() as r_port_in:
            yield r_port_in
            d01 = sample_delta_hito0_1(self.rng)
            t_port_in_start = self.env.now
            yield self.env.timeout(d01)
            t_port_in_end = self.env.now
            self.metricas_recursos["porteros"]["tiempo_activo"] += d01
            self.port_ops.append({"start": t_port_in_start, "end": t_port_in_end, "hold": d01, "tipo": "entrada"})
            self.metricas_recursos["porteros"]["operaciones"] += 1

        # Reserva patio equivalente (2) desde H1 hasta el FINAL (tras H2→H3)
        yield from self._patio_eq_get(2, f"T1 {camion_id}")
        try:
            self._registrar(f"{camion_id} toma patio (H1)", "t1_hito", {"camion": camion_id, "hito": 1})

            # H1→H2: Chequeador (carga/descarga)
            with self.cheq.request() as r_chk:
                yield r_chk
                d12 = sample_delta_hito1_2(self.rng)
                t_chk_start = self.env.now
                yield self.env.timeout(d12)
                t_chk_end = self.env.now
                self.metricas_recursos["chequeadores"]["tiempo_activo"] += d12
                self.cheq_ops.append({"start": t_chk_start, "end": t_chk_end, "hold": d12})
                self.metricas_recursos["chequeadores"]["operaciones"] += 1

            # H2→H3: Portería (salida)
            with self.porteria.request() as r_port_out:
                yield r_port_out
                d23 = sample_delta_hito2_3(self.rng)
                t_port_out_start = self.env.now
                yield self.env.timeout(d23)
                t_port_out_end = self.env.now
                self.metricas_recursos["porteros"]["tiempo_activo"] += d23
                self.port_ops.append({"start": t_port_out_start, "end": t_port_out_end, "hold": d23, "tipo": "salida"})
                self.metricas_recursos["porteros"]["operaciones"] += 1
        finally:
            self._patio_eq_put(2, f"T1 {camion_id}")

        t_fin = self.env.now
        dur = t_fin - t_inicia
        self.t1_eventos.append({
            "camion_id": camion_id, "inicio_min": t_inicia, "fin_min": t_fin,
            "inicio_hhmm": hhmm_dias(cfg.get("shift_start_min", 0) + t_inicia),
            "fin_hhmm": hhmm_dias(cfg.get("shift_start_min", 0) + t_fin),
            "modo": "T1", "hitos": [0, 1, 2, 3], "tiempo_min": dur,
            "pre_asignados": 0, "post_cargados": 0, "num_pallets": 0,
            "fusionados": 0, "corregidos": 0, "cajas_pre": 0, "cajas_pick_mixto": 0,
            "cajas_pickeadas_detalle": {
                "pallets_mixtos": [], "pallets_completos": [],
                "total_cajas_mixtas": 0, "total_cajas_completas": 0,
            },
        })
        self.eventos.append({
            "camion_id": camion_id, "vuelta": None,
            "inicio_min": t_inicia, "fin_min": t_fin,
            "inicio_hhmm": hhmm_dias(cfg.get("shift_start_min", 0) + t_inicia),
            "fin_hhmm": hhmm_dias(cfg.get("shift_start_min", 0) + t_fin),
            "modo": "T1", "tiempo_min": dur,
            "pre_asignados": 0, "post_cargados": 0, "num_pallets": 0,
            "fusionados": 0, "corregidos": 0, "cajas_pre": 0, "cajas_pick_mixto": 0,
            "cajas_pickeadas_detalle": {
                "pallets_mixtos": [], "pallets_completos": [],
                "total_cajas_mixtas": 0, "total_cajas_completas": 0,
            },
        })
        self._registrar(f"{camion_id} completa H0→H3 (T1)", "t1_fin", {
            "camion": camion_id, "duracion": _fmt(dur)
        })

    # ----------------------------- Generador T1 --------------------------------
    def _generador_T1(self):
        if not self.cfg.get("t1_habilitado", True):
            return
        turno_ini = self.cfg.get("shift_start_min", 0)
        turno_fin_abs = self.cfg.get("shift_end_min", 1440)
        duracion_turno = max(0, turno_fin_abs - turno_ini)

        params = self.cfg.get("t1_cantidad_dia_weibull") or self.cfg.get("t1_llegadas_weibull", {})
        max_por_dia = self.cfg.get("t1_max_por_dia")
        N = sample_num_camiones_t1_dia(self.rng, params, max_camiones=max_por_dia)
        if self.cfg.get("debug", False):
            print(f"=== 🚚 T1: cantidad del día (Weibull→entero) = {N}  (máx={max_por_dia}) ===")
        if N <= 0 or duracion_turno <= 0:
            return

        arrivals = sorted(U_rng(self.rng, 0.0, float(duracion_turno)) for _ in range(N))
        pref = self.cfg.get("t1_prefijo_id", "T1")
        t_prev = self.env.now
        for i, t_abs in enumerate(arrivals, start=1):
            dt = max(0.0, t_abs - t_prev)
            yield self.env.timeout(dt)
            self.t1_contador += 1
            cid = f"{pref}-{self.t1_contador:04d}"
            #self._dbg("⬅️  LLEGA camión T1 (generador)", camion=cid, t_abs=f"{t_abs:.2f}")
            self.env.process(self._proceso_camion_T1(cid))
            t_prev = t_abs


    
    # --------------------------------- Driver ---------------------------------
    def run(self, asignaciones, seed=None, estado_inicial_dia=None):
        self.rng = make_rng(seed)
        salidas, retornos, salidas_v1_pendientes = [], [], []
        self.env.process(self._gestor_turnos())
        self.env.process(self._generador_T1())

        pendientes_v1 = set()
        if isinstance(estado_inicial_dia, dict):
            for c in estado_inicial_dia.get("camiones_en_ruta", []) or []:
                if not c.get("hora_estimada_regreso"):
                    cid = c.get("camion_id")
                    if cid:
                        pendientes_v1.add(cid)

        if self.cfg.get("debug", False):
            print("\n=== 📦 ASIGNACIONES DÍA (entrada) ===")
            for a in asignaciones:
                cajas = sum(p.get("cajas", 0) for p in a["pallets"])
                print(f" - Camión {a['camion_id']}: pallets={len(a['pallets'])} cajas={cajas} vuelta={a.get('vuelta', 2)}")
            if pendientes_v1:
                print(f"=== 🚚 V1 pendientes de salida (día): {sorted(pendientes_v1)} ===")

        # 1) Inicializar chequeo global
        for a in asignaciones:
            total = len(a["pallets"])
            for idx, p in enumerate(a["pallets"], start=1):
                p["_chequed"] = False
                p["_evt_chk"] = self.env.event()
                self.queue_chequeo.put((p, a["camion_id"], a.get("vuelta", 2), idx, total))

        def _cap_chequeador_max():
            base = int(self.cfg.get("cap_chequeador", 2))
            mx = base
            for sh in (self.cfg.get("shifts_day") or []):
                try:
                    mx = max(mx, int(sh.get("caps", {}).get("chequeador", base)))
                except Exception:
                    pass
            return mx
        
        for wid in range(_cap_chequeador_max()):
            self.env.process(self._worker_chequeo_global(wid))

        # 2) Agrupar lotes por camión
        itinerarios = defaultdict(list)
        offset_por_camion = {}
        for a in asignaciones:
            itinerarios[a["camion_id"]].append({
                "vuelta": int(max(2, a.get("vuelta", 2))),
                "pallets": a["pallets"],
            })
            offset_por_camion.setdefault(a["camion_id"], int(a.get("offset_idx", 0)))
        for cid in itinerarios: itinerarios[cid].sort(key=lambda L: L["vuelta"])

        evt_salio_v1 = {}
        def _proc_despachar_v1(cid: str):
            with self.patio_camiones.request() as slot:
                yield slot
                with self.movi.request() as m:
                    yield m
                    t_m = U_rng(self.rng, *self.cfg.get("t_mover_camion", (1.3, 1.4)))
                    t_movi_start = self.env.now
                    yield self.env.timeout(t_m)
                    t_movi_end = self.env.now
                    self.metricas_recursos["movilizadores"]["tiempo_activo"] += t_m
                    self.movi_ops.append({"start": t_movi_start, "end": t_movi_end, "hold": t_m})
                    self.metricas_recursos["movilizadores"]["operaciones"] += 1
            ts = self.env.now
            salidas_v1_pendientes.append({"camion_id": cid, "vuelta": 1, "hora_salida": hhmm_dias(self.cfg.get("shift_start_min", 0) + ts)})
            ev = evt_salio_v1.get(cid)
            if ev and not ev.triggered: ev.succeed()

        for cid in pendientes_v1:
            evt_salio_v1[cid] = self.env.event()
            self.env.process(_proc_despachar_v1(cid))

        def camion_runner(camion_id, lotes, offset_idx):
            base_travel_min = sample_lognormal_retorno_camion(self.rng)
            if camion_id in evt_salio_v1:
                yield evt_salio_v1[camion_id]
                arrive_min = base_travel_min
            else:
                arrive_min = base_travel_min
            arrive_hhmm = hhmm_dias(self.cfg.get("shift_start_min", 0) + self.env.now + arrive_min)
            #self._dbg(f"🛣️ EN RUTA V{lotes[0]['vuelta']}: ETA llegada",
                      #camion=camion_id, eta_min=f"{arrive_min:.2f}", eta_hhmm=arrive_hhmm)
            yield self.env.timeout(max(0.0, arrive_min))
            #self._dbg(f"⬅️  LLEGA camión V{lotes[0]['vuelta']}", camion=camion_id)

            for i, lote in enumerate(lotes):
                v = lote["vuelta"]; pallets = lote["pallets"]
                t_fin = (yield self.env.process(self.procesar_vuelta(camion_id, pallets, vuelta=v)))
                salidas.append({"camion_id": camion_id, "vuelta": v, "hora_salida": hhmm_dias(self.cfg.get("shift_start_min", 0) + t_fin)})

                ret_min = sample_lognormal_retorno_camion(self.rng)
                ret_eta_hhmm = hhmm_dias(self.cfg.get("shift_start_min", 0) + self.env.now + ret_min)
                #self._dbg("🛣️  RETORNA: ETA retorno", camion=camion_id, vuelta=v, eta_min=f"{ret_min:.2f}", eta_hhmm=ret_eta_hhmm)
                yield self.env.timeout(max(0.0, ret_min))
                self._registrar(f"camion {camion_id} retorna tras vuelta {v}", "retorno_camion", {"camion": camion_id, "vuelta": v})
                retornos.append({"camion_id": camion_id, "vuelta": v, "hora_retorno": hhmm_dias(self.cfg.get("shift_start_min", 0) + self.env.now)})
                if i + 1 < len(lotes):
                    next_v = lotes[i + 1]["vuelta"]
                    #self._dbg(f"⬅️  LLEGA camión V{next_v}", camion=camion_id)

        for cid, lotes in itinerarios.items():
            self.env.process(camion_runner(cid, lotes, offset_por_camion.get(cid, 0)))

        # Corre solo la duración del turno
        turno_ini = self.cfg.get("shift_start_min", 0)
        turno_fin_abs = self.cfg.get("shift_end_min", 1440)
        duracion_turno = max(0, turno_fin_abs - turno_ini)
        self.env.run(until=duracion_turno)

        total_linea = max((e["tiempo_min"] for e in self.linea_tiempo), default=0)
        total_fin = max(max((e.get("fin_min", 0) for e in self.eventos), default=0), total_linea)

        ocupacion = calcular_ocupacion_recursos(self, self.cfg, tiempo_total_turno=max(total_fin, duracion_turno))

        if self.cfg.get("debug", False):
            print("\n=== 📊 RESUMEN DÍA ===")
            print(f"Camiones procesados (eventos en patio): {len(self.eventos)}")
            print(f"Camiones T1 generados: {self.t1_contador}")
            print(f"Ocupación recursos:")
            for k, v in ocupacion.items():
                pct = v.get("porcentaje_ocupacion", 0); t_act = v.get("tiempo_activo", 0); ops  = v.get("operaciones", 0)
                print(f" - {k:14s} -> {pct:5.1f}%  activo={_fmt(t_act)}  ops={ops}")
            print("=====================================\n")

        return {
            "centro_eventos": self.eventos,
            "t1_eventos": self.t1_eventos,
            "grua_operaciones": self.grua_ops,
            "ocupacion_recursos": ocupacion,
            "timeline": self.linea_tiempo,
            "turno_fin_real": hhmm_dias(self.cfg.get("shift_start_min", 0) + total_fin),
            "cronograma_dia": formatear_cronograma_dia(self.eventos),
            "t1_generados": self.t1_contador,
            "nueva_salida_camiones": salidas,
            "retornos_camiones": retornos,
            "num_vueltas": sum(1 for e in self.eventos if e.get("modo") == "carga_dia"),
        }
