# app/simulations/night_shift/planning.py
from .config import WEIBULL_CAJAS_PARAMS, DEFAULT_CONFIG
from .rng import RI_rng
from .dists import sample_weibull_cajas

# IDs reales disponibles para camiones (se reusan cíclicamente en vueltas 2+)
CAMION_IDS = [
    "E44","E45","E46","E47","E48","E49","E50","E51","E52","E55",
    "E71","E72","E73","E74","E75","E76","E77","E78","E79","E80",
    "E81","E82","E83","E87","E89","E90","E91","E92","E93","E94",
    "E95","E96","E97","E98","E99","E100","E101","E102","E103","E104"
]

def asignar_ids_camiones(plan):
    """Asigna IDs reales a los camiones, reutilizando los de V1 en vueltas posteriores."""
    plan_con_ids = []
    ids_v1 = []

    for vuelta, asignaciones in plan:
        asign_con_id = []
        if vuelta == 1:
            for idx, pallets_cam in enumerate(asignaciones):
                camion_id = CAMION_IDS[idx] if idx < len(CAMION_IDS) else f"E{105 + (idx - len(CAMION_IDS))}"
                ids_v1.append(camion_id)
                asign_con_id.append({"camion_id": camion_id, "pallets": pallets_cam})
        else:
            for idx, pallets_cam in enumerate(asignaciones):
                camion_id = ids_v1[idx % len(ids_v1)]
                asign_con_id.append({"camion_id": camion_id, "pallets": pallets_cam})

        plan_con_ids.append((vuelta, asign_con_id))
    return plan_con_ids

def generar_pallets_desde_cajas_dobles(total_cajas_facturadas, cajas_para_pick, cfg, rng):
    """Genera pallets mixtos y completos priorizando más cajas por pallet."""
    cajas_completas = max(0, total_cajas_facturadas - cajas_para_pick)

    pallets_mixtos, rest = [], cajas_para_pick
    while rest > 0:
        mn, mx = cfg.get("cajas_por_pallet_mixto", (25, 45))
        c = RI_rng(rng, mn, mx)
        c = min(c, int(rest))
        pallets_mixtos.append({"mixto": True, "cajas": c, "id": f"MX{len(pallets_mixtos)+1}"})
        rest -= c

    pallets_completos, rest = [], cajas_completas
    while rest > 0:
        mn, mx = cfg.get("cajas_por_pallet_completo", (35, 55))
        c = RI_rng(rng, mn, mx)
        c = min(c, int(rest))
        pallets_completos.append({"mixto": False, "cajas": c, "id": f"CP{len(pallets_completos)+1}"})
        rest -= c

    pallets = pallets_mixtos + pallets_completos
    resumen = {
        "pallets_mixtos": len(pallets_mixtos),
        "pallets_completos": len(pallets_completos),
        "cajas_promedio_mixto": (sum(p["cajas"] for p in pallets_mixtos)/len(pallets_mixtos)) if pallets_mixtos else 0,
        "cajas_promedio_completo": (sum(p["cajas"] for p in pallets_completos)/len(pallets_completos)) if pallets_completos else 0,
    }
    return pallets, resumen

def generar_capacidades_camiones(num_camiones, rng):
    caps = []
    for _ in range(num_camiones):
        cap = sample_weibull_cajas(rng, WEIBULL_CAJAS_PARAMS["alpha"], WEIBULL_CAJAS_PARAMS["beta"], WEIBULL_CAJAS_PARAMS["gamma"])
        caps.append(cap)
    return sorted(caps, reverse=True)

def construir_plan_desde_pallets(pallets, cfg, rng):
    """
    Construye un plan de vueltas (1 = carga, 2+ = staging) con capacidades Weibull.
    Mantiene la misma heurística y reutilización cíclica de camiones que tenías.
    """
    if not pallets:
        return []

    max_camiones = cfg.get("camiones", DEFAULT_CONFIG["camiones"])
    caps_v1 = generar_capacidades_camiones(max_camiones, rng)
    cajas_totales = sum(p["cajas"] for p in pallets)

    # clasificar pallets
    por_tam = {
        "grandes":  sorted([p for p in pallets if p["cajas"] >= 60], key=lambda x: x["cajas"], reverse=True),
        "medianos": sorted([p for p in pallets if 30 <= p["cajas"] < 60], key=lambda x: x["cajas"], reverse=True),
        "pequeños": sorted([p for p in pallets if p["cajas"] < 30], key=lambda x: x["cajas"], reverse=True),
    }

    # vuelta 1 (80–90% de cada camión)
    cap_total_v1 = sum(c * 0.85 for c in caps_v1)
    n_cam_v1 = min(max_camiones, max(1, int(cajas_totales / (cap_total_v1 / max_camiones))))
    asign_v1 = []

    for i in range(n_cam_v1):
        if i >= len(caps_v1): break
        cap = caps_v1[i]
        tgt_min, tgt_max = int(cap * 0.80), int(cap * 0.90)
        cajas_acum, asign_cam = 0, []

        for tipo in ("grandes", "medianos", "pequeños"):
            while por_tam[tipo] and cajas_acum < tgt_min and cajas_acum < tgt_max:
                pal = por_tam[tipo][0]
                if cajas_acum + pal["cajas"] <= tgt_max + 50:
                    asign_cam.append(por_tam[tipo].pop(0))
                    cajas_acum += pal["cajas"]
                else:
                    break
        if asign_cam:
            asign_v1.append(asign_cam)

    sobrantes = por_tam["grandes"] + por_tam["medianos"] + por_tam["pequeños"]
    plan = [(1, asign_v1)]

    # vueltas 2+ (staging, 70–80%)
    vuelta = 2
    pallets_rest = list(sobrantes)
    while pallets_rest:
        caps = generar_capacidades_camiones(max_camiones, rng)
        cajas_v = sum(p["cajas"] for p in pallets_rest)

        cam_nec, cubiertas = 0, 0
        for i, cap in enumerate(caps):
            cubiertas += cap * 0.75
            cam_nec = i + 1
            if cubiertas >= cajas_v:
                break

        camiones = min(cam_nec, max_camiones)
        caps = caps[:camiones]

        grandes = [p for p in pallets_rest if p["cajas"] >= 60]
        otros   = [p for p in pallets_rest if p["cajas"] < 60]
        rng.shuffle(grandes)
        rng.shuffle(otros)

        asign_v = []
        for i in range(camiones):
            cap = caps[i]
            tgt_min, tgt_max = int(cap * 0.70), int(cap * 0.80)
            cajas_acum, cam = 0, []

            while grandes and cajas_acum < tgt_min:
                pal = grandes[0]
                if cajas_acum + pal["cajas"] <= tgt_max + 50:
                    cam.append(grandes.pop(0)); cajas_acum += pal["cajas"]
                else:
                    break
            while otros and cajas_acum < tgt_max:
                pal = otros[0]
                if cajas_acum + pal["cajas"] <= tgt_max + 30:
                    cam.append(otros.pop(0)); cajas_acum += pal["cajas"]
                else:
                    break
            if cam:
                asign_v.append(cam)

        pallets_rest = grandes + otros
        if asign_v:
            plan.append((vuelta, asign_v)); vuelta += 1
        else:
            # no se pudo asignar más sin sobrepasar tolerancia
            break

        if vuelta > 5:  # mismo corte de seguridad que usabas
            break

    return asignar_ids_camiones(plan)
    