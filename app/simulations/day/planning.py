# app/simulations/day/planning.py
from collections import defaultdict

def construir_asignaciones_desde_estado(estado_inicial_dia):
    asignaciones = []
    pallets_por_camion = defaultdict(list)

    for p in estado_inicial_dia.get("pallets_listos_para_carga", []) or []:
        cid = p.get("camion_asignado") or p.get("camion") or p.get("camion_id")
        v   = int(max(2, p.get("vuelta_origen", 2)))
        pallets = (p.get("pallets_mixtos") or []) + (p.get("pallets_completos") or [])
        if cid and pallets:
            pallets_por_camion[cid].append({"vuelta": v, "pallets": pallets})

    cam_en_ruta = [c.get("camion_id") for c in (estado_inicial_dia.get("camiones_en_ruta") or []) if c.get("camion_id")]

    if not cam_en_ruta:
        camiones = sorted(pallets_por_camion.keys())
    else:
        camiones = cam_en_ruta + [cid for cid in pallets_por_camion.keys() if cid not in cam_en_ruta]

    for i, cid in enumerate(camiones):
        lotes = sorted(pallets_por_camion.get(cid, []), key=lambda x: x["vuelta"])
        for lote in lotes:
            asignaciones.append({
                "camion_id": cid,
                "pallets":   lote["pallets"],
                "vuelta":    lote["vuelta"],
                "offset_idx": i,
            })
    return asignaciones

def _resumen_pre_turno(asignaciones):
    por_vuelta = defaultdict(list)
    for a in asignaciones:
        cajas = sum(p.get("cajas", 0) for p in a["pallets"])
        por_vuelta[a.get("vuelta", 2)].append({
            "camion_id": a["camion_id"], "pallets": len(a["pallets"]), "cajas": cajas,
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

__all__ = ["construir_asignaciones_desde_estado", "_resumen_pre_turno"]
