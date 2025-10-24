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
    salidas_idx = getattr(centro, "salidas_por_camion", [])
    for asign in v1:
        cid = asign["camion_id"]
        evs = [e for e in centro.eventos if e["camion_id"] == cid and e["vuelta"] == 1]
        if evs:
            continue

        ev = evs[0]
        salida_info = salidas_idx.get(cid)
        if salida_info:
            dur_horas = salida_info["duracion_ruta_est_min"] / 60.0
            estado["camiones_en_ruta"].append({
                "camion_id": cid,
                "salio_noche_fin": ev["fin_hhmm"],
                "cajas_cargadas_v1": ev["cajas_pre"],
                "hora_salida" : salida_info["salida_hhmm"],
                "hora_estimada_regreso": salida_info["retorno_est_hhmm"],
                "tiempo_estimado_retorno_horas": round(dur_horas, 2),
                "proxima_vuelta_asignada": None
            })
        else:
            estado["camiones_en_ruta"].append({
                "camion_id": cid,
                "salio_noche_fin": ev["fin_hhmm"],
                "cajas_cargadas_v1": ev["cajas_pre"],
                "hora_salida": ev["fin_hhmm"],
                "hora_estimada_regreso": None,
                "tiempo_estimado_retorno_horas": 8,  # valor por defecto
                "proximo_vuelta_asignada": None
            })


    # Pallets listos (staging nocturno)
    staging = [(v, asign) for (v, asign) in plan if v > 1]
    for vnum, asigns in staging:
        for asign in asigns:
            cid = asign["camion_id"]
            evs = [e for e in centro.eventos if e["camion_id"] == cid and e["vuelta"] == vnum]
            if evs:
                ev = evs[0]
                estado["pallets_listos_para_carga"].append({
                    "vuelta_origen": vnum,
                    "camion_asignado": ev["camion_id"],
                    "pallets_mixtos": ev["cajas_pickeadas_detalle"]["pallets_mixtos"],
                    "pallets_completos": ev["cajas_pickeadas_detalle"]["pallets_completos"],
                    "total_cajas": ev["cajas_pre"],
                    "estado": "por_chequear",
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

    salidas_list = getattr(centro, "salidas_camiones", [])
    if salidas_list:
        # Ordenamos por tiempo estimado de retorno
        orden = sorted(salidas_list, key=lambda x: x["retorno_est_min"])
        for i, s in enumerate(orden):
            # Asignación simple de vuelta del día (si hay staging)
            vuelta_asignada = staging[i % len(staging)][0] if staging else None
            estado["cronograma_retornos"].append({
                "camion_id": s["camion_id"],
                "hora_retorno_estimada": s["retorno_est_hhmm"],
                "siguiente_carga_disponible": bool(staging),
                "vuelta_asignada": vuelta_asignada
            })
    else:
        hora_base = 8  # 08:00
        for i, cam in enumerate(estado["camiones_en_ruta"]):
            estado["cronograma_retornos"].append({
                "camion_id": cam["camion_id"],
                "hora_retorno_estimada": f"{hora_base + (i * 0.5):.1f}:00",
                "siguiente_carga_disponible": len(estado["pallets_listos_para_carga"]) > i,
                "vuelta_asignada": staging[i % len(staging)][0] if staging else None
            })

    # --- Fallback: si 'camiones_en_ruta' quedó vacío, inferir desde pallets listos ---
    if not estado["camiones_en_ruta"]:
        vistos = set()
        for p in estado["pallets_listos_para_carga"]:
            cid = p.get("camion_asignado") or p.get("camion") or p.get("camion_id")
            if cid and cid not in vistos:
                vistos.add(cid)
                estado["camiones_en_ruta"].append({
                    "camion_id": cid,
                    # sin salida registrada en noche: quedan en cola para el día
                    "hora_salida": None,
                    "hora_estimada_regreso": None,
                    "tiempo_estimado_retorno_horas": None,
                    "proximo_vuelta_asignada": None,
                })

    return estado
