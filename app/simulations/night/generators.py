# app/simulations/night_shift/generators.py
from .utils import RI_rng , sample_int_or_range_rng

def _emitir_palletes_por_cajas(rest_cajas, rango, mixto, rng, prefijo_id):
    pallets = []
    cont = 0
    a, b = rango
    while rest_cajas > 0:
        cont += 1
        # muestreo típico
        tam = RI_rng(rng, a, b)
        # respetar remanente
        if tam > rest_cajas:
            tam = rest_cajas
            if tam < a or tam > b:
                print(f"[Warn] Último pallet {prefijo_id}{cont} fuera de rango {rango}: cajas={tam}")
        pallets.append({"mixto": mixto, "cajas": tam, "id": f"{prefijo_id}{cont}"})
        rest_cajas -= tam
    return pallets, cont

def generar_pallets_desde_cajas_dobles(total_cajas_facturadas: int, cajas_para_pick: int, cfg, rng):
    total = max(int(total_cajas_facturadas), 0)
    pick = max(int(cajas_para_pick), 0)
    if pick > total:
        print(f"[Warn] cajas_para_pick({pick}) > total_cajas_facturadas({total}). Se capea a {total}.")
        pick = total
    comp = total - pick

    # Mixtos
    pallets_mix, n_mix = _emitir_palletes_por_cajas(
        rest_cajas=pick,
        rango=cfg["cajas_mixto"],
        mixto=True,
        rng=rng,
        prefijo_id="M"
    )
    # Completos
    pallets_comp, n_comp = _emitir_palletes_por_cajas(
        rest_cajas=comp,
        rango=cfg["cajas_completo"],
        mixto=False,
        rng=rng,
        prefijo_id="C"
    )

    pallets = pallets_mix + pallets_comp
    rng.shuffle(pallets)

    # Validación de sumas
    suma_cajas = sum(p["cajas"] for p in pallets)
    if suma_cajas != total:
        print(f"[Warn] Suma de cajas generadas {suma_cajas} != total_cajas_facturadas {total}")

    return pallets, {"pallets_mixtos": n_mix, "pallets_completos": n_comp}

def construir_plan_desde_pallets(pallets, cfg, rng):
    
    
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