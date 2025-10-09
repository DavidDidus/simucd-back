# app/simulations/night_shift/generators.py
from .config import WEIBULL_CAJAS_PARAMS, DEFAULT_CONFIG
from .utils import sample_weibull_cajas

# IDs de camiones disponibles
CAMION_IDS = [
    "E44", "E45", "E46", "E47", "E48", "E49", "E50", "E51", "E52", "E55",
    "E71", "E72", "E73", "E74", "E75", "E76", "E77", "E78", "E79", "E80",
    "E81", "E82", "E83", "E87", "E89", "E90", "E91", "E92", "E93", "E94",
    "E95", "E96", "E97", "E98", "E99", "E100", "E101", "E102", "E103", "E104"
]

def asignar_ids_camiones(plan):
    """Asigna IDs reales a los camiones, reutilizando los de V1 en vueltas posteriores"""
    plan_con_ids = []
    camiones_v1_ids = []  # IDs de camiones usados en V1
    
    for vuelta, asignaciones in plan:
        asignaciones_con_ids = []
        
        if vuelta == 1:
            # Primera vuelta: asignar IDs nuevos
            for cam_index, pallets_cam in enumerate(asignaciones):
                if cam_index < len(CAMION_IDS):
                    camion_id = CAMION_IDS[cam_index]
                else:
                    # Si se agotan los IDs, generar más con el mismo formato
                    camion_id = f"E{105 + (cam_index - len(CAMION_IDS))}"
                
                camiones_v1_ids.append(camion_id)  # Guardar para reutilizar
                
                asignaciones_con_ids.append({
                    'camion_id': camion_id,
                    'pallets': pallets_cam
                })
        else:
            # Vueltas 2+: REUTILIZAR camiones de V1 
            for cam_index, pallets_cam in enumerate(asignaciones):
                if cam_index < len(camiones_v1_ids):
                    # USAR EL MISMO CAMION DE V1
                    camion_id = camiones_v1_ids[cam_index]
                else:
                    # Si necesitamos más camiones que los de V1, usar camiones adicionales
                    # Pero esto debería ser raro si la lógica está bien
                    id_adicional = len(camiones_v1_ids) + (cam_index - len(camiones_v1_ids))
                    if id_adicional < len(CAMION_IDS):
                        camion_id = CAMION_IDS[id_adicional]
                    else:
                        camion_id = f"E{105 + (id_adicional - len(CAMION_IDS))}"
                    print(f"[WARNING] Vuelta {vuelta}: Usando camión adicional {camion_id} (índice {cam_index})")
                
                asignaciones_con_ids.append({
                    'camion_id': camion_id,
                    'pallets': pallets_cam
                })
        
        plan_con_ids.append((vuelta, asignaciones_con_ids))
    
    print(f"[DEBUG] Camiones V1: {camiones_v1_ids}")
    return plan_con_ids

def generar_pallets_desde_cajas_dobles(total_cajas_facturadas, cajas_para_pick, cfg, rng):
    """
    Genera pallets con MÁS CAJAS por pallet para llenar mejor los camiones
    """
    cajas_completas = total_cajas_facturadas - cajas_para_pick
    
    # *** AUMENTAR CAJAS POR PALLET MIXTO ***
    pallets_mixtos = []
    cajas_restantes_mixtas = cajas_para_pick
    
    while cajas_restantes_mixtas > 0:
        # Usar rango más alto de cajas por pallet
        min_cajas = cfg.get("cajas_por_pallet_mixto", [25, 45])[0]
        max_cajas = cfg.get("cajas_por_pallet_mixto", [25, 45])[1]
        
        cajas_este_pallet = rng.randint(min_cajas, max_cajas)
        cajas_este_pallet = min(cajas_este_pallet, cajas_restantes_mixtas)
        
        pallets_mixtos.append({
            "mixto": True,
            "cajas": cajas_este_pallet,
            "id": f"MX{len(pallets_mixtos)+1}"
        })
        
        cajas_restantes_mixtas -= cajas_este_pallet
    
    # *** AUMENTAR CAJAS POR PALLET COMPLETO ***
    pallets_completos = []
    cajas_restantes_completas = cajas_completas
    
    while cajas_restantes_completas > 0:
        # Usar rango más alto de cajas por pallet
        min_cajas = cfg.get("cajas_por_pallet_completo", [35, 55])[0]
        max_cajas = cfg.get("cajas_por_pallet_completo", [35, 55])[1]
        
        cajas_este_pallet = rng.randint(min_cajas, max_cajas)
        cajas_este_pallet = min(cajas_este_pallet, cajas_restantes_completas)
        
        pallets_completos.append({
            "mixto": False,
            "cajas": cajas_este_pallet,
            "id": f"CP{len(pallets_completos)+1}"
        })
        
        cajas_restantes_completas -= cajas_este_pallet
    
    todos_los_pallets = pallets_mixtos + pallets_completos
    
    resumen = {
        "pallets_mixtos": len(pallets_mixtos),
        "pallets_completos": len(pallets_completos),
        "cajas_promedio_mixto": sum(p["cajas"] for p in pallets_mixtos) / len(pallets_mixtos) if pallets_mixtos else 0,
        "cajas_promedio_completo": sum(p["cajas"] for p in pallets_completos) / len(pallets_completos) if pallets_completos else 0
    }
    
    return todos_los_pallets, resumen

# *** FUNCIÓN PARA GENERAR CAPACIDADES WEIBULL ***
def generar_capacidades_camiones(num_camiones,rng):
    capacidades = []
    for _ in range(num_camiones):
        cap = sample_weibull_cajas(
            rng,
            WEIBULL_CAJAS_PARAMS["alpha"],
            WEIBULL_CAJAS_PARAMS["beta"], 
            WEIBULL_CAJAS_PARAMS["gamma"]
        )
        capacidades.append(cap)
    return sorted(capacidades, reverse=True)

def construir_plan_desde_pallets(pallets, cfg, rng):
    """
    Construye plan basado en capacidades reales de la distribución Weibull
    """
    if not pallets:
        return []
    
    # *** VUELTA 1: ASIGNACIÓN PRINCIPAL ***
    max_camiones = cfg.get("camiones", DEFAULT_CONFIG["camiones"])
    capacidades_v1 = generar_capacidades_camiones(max_camiones, rng)
    
    cajas_totales = sum(p["cajas"] for p in pallets)
    
    # Asignación para vuelta 1 (código existente...)
    asignaciones_v1 = []
    pallets_disponibles = pallets[:]
    
    # Ordenar pallets para mejor distribución
    pallets_por_tamaño = {
        'grandes': sorted([p for p in pallets_disponibles if p["cajas"] >= 60], 
                         key=lambda x: x["cajas"], reverse=True),
        'medianos': sorted([p for p in pallets_disponibles if 30 <= p["cajas"] < 60], 
                          key=lambda x: x["cajas"], reverse=True),
        'pequeños': sorted([p for p in pallets_disponibles if p["cajas"] < 30], 
                          key=lambda x: x["cajas"], reverse=True)
    }
    
    # Determinar cuántos camiones usar en V1
    capacidad_total_v1 = sum(cap * 0.85 for cap in capacidades_v1)  # 85% utilización
    camiones_necesarios_v1 = min(max_camiones, max(1, int(cajas_totales / (capacidad_total_v1 / max_camiones))))
    
    # Asignar pallets a V1
    for i in range(camiones_necesarios_v1):
        if i >= len(capacidades_v1):
            break
            
        capacidad_camion = capacidades_v1[i]
        pallets_asignados = []
        cajas_acumuladas = 0
        
        # Target: usar 80-90% de la capacidad
        target_min = int(capacidad_camion * 0.80)
        target_max = int(capacidad_camion * 0.90)
        
        # Estrategia de llenado balanceada
        for tipo in ['grandes', 'medianos', 'pequeños']:
            while (cajas_acumuladas < target_max and 
                   pallets_por_tamaño[tipo] and 
                   cajas_acumuladas < target_min):
                
                pallet = pallets_por_tamaño[tipo][0]
                if cajas_acumuladas + pallet["cajas"] <= target_max + 50:  # Tolerancia
                    pallets_asignados.append(pallets_por_tamaño[tipo].pop(0))
                    cajas_acumuladas += pallet["cajas"]
                else:
                    break
        
        if pallets_asignados:
            asignaciones_v1.append(pallets_asignados)
    
    # *** VERIFICAR PALLETS SOBRANTES PARA VUELTAS ADICIONALES ***
    pallets_sobrantes = (pallets_por_tamaño['grandes'] + 
                        pallets_por_tamaño['medianos'] + 
                        pallets_por_tamaño['pequeños'])
    
    plan_final = [(1, asignaciones_v1)]
    
    if pallets_sobrantes:
        cajas_sobrantes = sum(p["cajas"] for p in pallets_sobrantes)
        
        # *** CREAR VUELTAS ADICIONALES CON DISTRIBUCIÓN WEIBULL ***
        vuelta_num = 2
        pallets_restantes = pallets_sobrantes[:]
        
        while pallets_restantes:
            
            # *** CALCULAR CAMIONES NECESARIOS USANDO WEIBULL ***
            cajas_esta_vuelta = sum(p["cajas"] for p in pallets_restantes)
            
              # *** USAR LA MISMA CAPACIDAD DE CAMIONES QUE V1 ***
            # Las vueltas 2+ tienen acceso a todos los camiones, no solo la mitad
            max_camiones_staging = max_camiones  # MISMA capacidad que V1
            capacidades_staging = generar_capacidades_camiones(max_camiones_staging, rng)
            
            # Calcular cuántos camiones realmente necesitamos
            camiones_necesarios = 0
            cajas_cubiertas_staging = 0
            
            for i, capacidad in enumerate(capacidades_staging):
                cajas_cubiertas_staging += capacidad * 0.75  # 75% utilización para staging (un poco menos que V1)
                camiones_necesarios = i + 1
                if cajas_cubiertas_staging >= cajas_esta_vuelta:
                    break
            
            # *** NO LIMITAR A LA MITAD - USAR TODOS LOS CAMIONES NECESARIOS ***
            camiones_staging = min(camiones_necesarios, max_camiones_staging)
            capacidades_a_usar = capacidades_staging[:camiones_staging]
            
            # *** ASIGNACIÓN INTELIGENTE PARA STAGING ***
            asignaciones_vuelta = []
            
            # Ordenar pallets restantes por tamaño
            pallets_restantes_grandes = [p for p in pallets_restantes if p["cajas"] >= 60]
            pallets_restantes_otros = [p for p in pallets_restantes if p["cajas"] < 60]
            
            rng.shuffle(pallets_restantes_grandes)
            rng.shuffle(pallets_restantes_otros)
            
            for i in range(camiones_staging):
                if i >= len(capacidades_a_usar):
                    break
                    
                capacidad_camion = capacidades_a_usar[i]
                pallets_este_camion = []
                cajas_acumuladas = 0
                
                # Target para staging: 70-80% de capacidad (más conservador que V1)
                target_min = int(capacidad_camion * 0.70)
                target_max = int(capacidad_camion * 0.80)
                
                # *** ESTRATEGIA MEJORADA: LLENAR EFICIENTEMENTE ***
                # 1. Primero intentar con pallets grandes
                while (cajas_acumuladas < target_min and pallets_restantes_grandes):
                    pallet = pallets_restantes_grandes[0]
                    if cajas_acumuladas + pallet["cajas"] <= target_max + 50:  # Tolerancia reducida
                        pallets_este_camion.append(pallets_restantes_grandes.pop(0))
                        cajas_acumuladas += pallet["cajas"]
                    else:
                        break
                
                # 2. Completar con pallets más pequeños
                while (cajas_acumuladas < target_max and pallets_restantes_otros):
                    pallet = pallets_restantes_otros[0]
                    if cajas_acumuladas + pallet["cajas"] <= target_max + 30:  # Tolerancia menor
                        pallets_este_camion.append(pallets_restantes_otros.pop(0))
                        cajas_acumuladas += pallet["cajas"]
                    else:
                        break
                
                if pallets_este_camion:
                    print(f"[DEBUG] V{vuelta_num} - Camión {i+1}: {len(pallets_este_camion)} pallets, {cajas_acumuladas:,} cajas")
                    asignaciones_vuelta.append(pallets_este_camion)
                else:
                    print(f"[DEBUG] V{vuelta_num} - Camión {i+1}: NO SE ASIGNARON PALLETS")
            
            # Actualizar pallets restantes
            pallets_restantes = pallets_restantes_grandes + pallets_restantes_otros
            
            if asignaciones_vuelta:
                plan_final.append((vuelta_num, asignaciones_vuelta))
                vuelta_num += 1
            else:
                # Si no se pudo crear asignación, salir para evitar bucle infinito
                if pallets_restantes:
                    print(f"[WARNING] {len(pallets_restantes)} pallets no pudieron ser asignados")
                break
            
            # Prevenir bucle infinito
            if vuelta_num > 5:
                print(f"[WARNING] Máximo de vueltas alcanzado")
                break
    
    return asignar_ids_camiones(plan_final)

