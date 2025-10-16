# app/simulations/night_shift/reporting.py

def generar_json_vueltas_camiones(plan, centro):
    """JSON con vueltas, camiones y detalle de pallets (con reutilización)."""
    data = {"vueltas": [], "info_reutilizacion": {"camiones_v1": [], "total_vueltas_por_camion": {}}}

    camiones_v1 = []
    if plan and plan[0][0] == 1:
        for asign in plan[0][1]:
            camiones_v1.append(asign["camion_id"])
    data["info_reutilizacion"]["camiones_v1"] = camiones_v1

    conteo = {}
    for vnum, _ in plan:
        eventos_v = [e for e in centro.eventos if e["vuelta"] == vnum]
        vinfo = {"numero_vuelta": vnum, "tipo_operacion": ("carga" if vnum == 1 else "staging"), "camiones": []}
        for ev in eventos_v:
            cid = ev["camion_id"]
            conteo[cid] = conteo.get(cid, 0) + 1
            vinfo["camiones"].append({
                "camion_id": cid,
                "cajas_asignadas": ev["cajas_pre"],
                "pre_asignados": ev["pre_asignados"],
                "pallets_detalle": ev["cajas_pickeadas_detalle"],
            })
        data["vueltas"].append(vinfo)

    data["info_reutilizacion"]["total_vueltas_por_camion"] = conteo
    reutilizados = [c for c, n in conteo.items() if n > 1]
    data["info_reutilizacion"]["estadisticas"] = {
        "total_camiones_unicos": len(conteo),
        "camiones_reutilizados": len(reutilizados),
        "tasa_reutilizacion": (len(reutilizados) / len(camiones_v1) * 100) if camiones_v1 else 0,
        "promedio_vueltas_por_camion": (sum(conteo.values()) / len(conteo)) if conteo else 0,
    }
    return data

def generar_estado_inicial_dia(plan, centro):
    """Estado para el turno día en base a lo preparado en la noche."""
    estado = {
        "camiones_en_ruta": [],
        "pallets_listos_para_carga": [],
        "cronograma_retornos": [],
        "vueltas_pendientes": []
    }

    if not plan:
        return estado

    # Camiones que salieron en V1 (carga noche)
    v1 = next((asign for (v, asign) in plan if v == 1), [])
    for asign in v1:
        evs = [e for e in centro.eventos if e["camion_id"] == asign["camion_id"] and e["vuelta"] == 1]
        if evs:
            ev = evs[0]
            estado["camiones_en_ruta"].append({
                "camion_id": ev["camion_id"],
                "salio_noche_fin": ev["fin_hhmm"],
                "cajas_cargadas_v1": ev["cajas_pre"],
                "tiempo_estimado_retorno_horas": 8,
                "proximo_vuelta_asignada": None
            })

    # Pallets listos (staging nocturno)
    staging = [(v, asign) for (v, asign) in plan if v > 1]
    for vnum, asigns in staging:
        for asign in asigns:
            evs = [e for e in centro.eventos if e["camion_id"] == asign["camion_id"] and e["vuelta"] == vnum]
            if evs:
                ev = evs[0]
                estado["pallets_listos_para_carga"].append({
                    "vuelta_origen": vnum,
                    "camion_asignado": ev["camion_id"],
                    "pallets_mixtos": ev["cajas_pickeadas_detalle"]["pallets_mixtos"],
                    "pallets_completos": ev["cajas_pickeadas_detalle"]["pallets_completos"],
                    "total_cajas": ev["cajas_pre"],
                    "estado": "listo_para_carga",
                    "preparado_noche_fin": ev["fin_hhmm"]
                })

    for vnum, asigns in staging:
        estado["vueltas_pendientes"].append({
            "numero_vuelta_original": vnum,
            "tipo": "carga_dia",
            "camiones_involucrados": [a["camion_id"] for a in asigns],
            "estado": "esperando_retorno_camiones",
            "pallets_disponibles": True,
            "dependencias": "camiones_regresen_de_ruta"
        })

    hora_base = 8  # 08:00
    for i, cam in enumerate(estado["camiones_en_ruta"]):
        estado["cronograma_retornos"].append({
            "camion_id": cam["camion_id"],
            "hora_retorno_estimada": f"{hora_base + (i * 0.5):.1f}:00",
            "siguiente_carga_disponible": len(estado["pallets_listos_para_carga"]) > i,
            "vuelta_asignada": staging[i % len(staging)][0] if staging else None
        })
    return estado
