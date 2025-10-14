# app/simulations/day/simulation.py
"""
Simulación principal del turno del día
"""
import simpy
import sys
import os

# Importaciones
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))
from app.simulations.night.utils import make_rng, hhmm_dias
from app.simulations.night.resources import Centro
from .utils import (calcular_tiempo_retorno, calcular_tiempo_carga_dia, 
                   formatear_cronograma_dia
                   ) 
from .config import get_day_config

def simular_turno_dia_desde_noche(resultado_noche, night_config, seed=None):
    """
    Simula el turno del día basado en los resultados del turno de la noche
    """
    # Configuración del día
    cfg_dia = get_day_config(night_config)
    rng = make_rng(seed)
    env = simpy.Environment()
    
    # Obtener estado inicial del día desde la noche
    estado_inicial = resultado_noche.get("estado_inicial_dia", {})
    
    if not estado_inicial:
        return {"error": "No hay estado inicial del día disponible"}
    
    print(f"[DIA DEBUG] Iniciando turno del día con:")
    print(f"   - Camiones en ruta: {len(estado_inicial['camiones_en_ruta'])}")
    print(f"   - Pallets listos: {len(estado_inicial['pallets_listos_para_carga'])}")
    print(f"   - Vueltas pendientes: {len(estado_inicial['vueltas_pendientes'])}")
    
    # Crear centro para el día (sin gates de pick)
    pick_gate = {0: {"target": 0, "count": 0, "event": env.event(), "done_time": 0}}
    pick_gate[0]["event"].succeed()
    
    centro_dia = Centro(env, cfg_dia, pick_gate, rng)
    
    # Procesar retornos de camiones
    camiones_procesados = procesar_retornos_camiones(
        env, centro_dia, estado_inicial, cfg_dia, rng
    )
    
    # Ejecutar simulación
    env.run()
    
    # Compilar y retornar resultados
    return compilar_resultados_dia(
        centro_dia, estado_inicial, camiones_procesados, cfg_dia
    )

def procesar_retornos_camiones(env, centro_dia, estado_inicial, cfg_dia, rng):
    """
    Procesa los retornos de camiones y programa sus cargas
    """
    camiones_procesados = 0
    
    for i, cronograma in enumerate(estado_inicial["cronograma_retornos"]):
        camion_id = cronograma["camion_id"]
        vuelta_asignada = cronograma["vuelta_asignada"]
        
        if vuelta_asignada:
            # Buscar pallets preparados para este camión
            pallets_camion = [p for p in estado_inicial["pallets_listos_para_carga"] 
                            if p["camion_asignado"] == camion_id and p["vuelta_origen"] == vuelta_asignada]
            
            if pallets_camion:
                pallet_data = pallets_camion[0]
                
                # Calcular tiempo de retorno
                tiempo_retorno = calcular_tiempo_retorno(i, cfg_dia, rng)
                
                print(f"[DIA DEBUG] Camión {camion_id} programado para retorno en minuto {tiempo_retorno} ({hhmm_dias(480 + tiempo_retorno)})")
                
                # Programar proceso de retorno y carga
                env.process(simular_retorno_y_carga_camion(
                    env, centro_dia, camion_id, pallet_data, tiempo_retorno, cfg_dia, rng
                ))
                camiones_procesados += 1
    
    return camiones_procesados

def simular_retorno_y_carga_camion(env, centro, camion_id, pallet_data, tiempo_retorno, cfg, rng):
    """
    Simula el retorno de un camión y su proceso de carga
    """
    # Esperar hasta el tiempo de retorno
    yield env.timeout(tiempo_retorno)
    
    inicio_carga = env.now
    print(f"[DIA] {hhmm_dias(480 + inicio_carga)} - Camión {camion_id} regresa de ruta")
    
    # Verificar pallets disponibles
    num_pallets = len(pallet_data.get("pallets_mixtos", [])) + len(pallet_data.get("pallets_completos", []))
    
    if num_pallets == 0:
        print(f"[DIA WARNING] Camión {camion_id} no tiene pallets asignados")
        return
    
    # Calcular tiempo de carga
    tiempo_carga_total = calcular_tiempo_carga_dia(num_pallets, cfg, rng)
    tiempo_por_pallet = tiempo_carga_total / num_pallets if num_pallets > 0 else 0
    
    print(f"[DIA] {hhmm_dias(480 + inicio_carga)} - Camión {camion_id} iniciando carga de {num_pallets} pallets (estimado: {tiempo_carga_total:.1f} min)")
    
    # Simular proceso de carga
    yield env.timeout(tiempo_carga_total)
    
    fin_carga = env.now
    print(f"[DIA] {hhmm_dias(480 + fin_carga)} - Camión {camion_id} terminó carga, saliendo con {pallet_data['total_cajas']} cajas")
    
    # Registrar evento
    registrar_evento_carga_dia(
        centro, camion_id, pallet_data, inicio_carga, fin_carga, 
        tiempo_carga_total, num_pallets, tiempo_por_pallet
    )

def registrar_evento_carga_dia(centro, camion_id, pallet_data, inicio_carga, fin_carga, 
                              tiempo_carga_total, num_pallets, tiempo_por_pallet):
    """
    Registra el evento de carga del día
    """
    evento_dia = {
        "vuelta": pallet_data["vuelta_origen"],
        "camion_id": camion_id,
        "cajas_pre": pallet_data["total_cajas"],
        "inicio_min": inicio_carga,
        "fin_min": fin_carga,
        "tiempo_min": tiempo_carga_total,
        "inicio_hhmm": hhmm_dias(480 + inicio_carga),
        "fin_hhmm": hhmm_dias(480 + fin_carga),
        "modo": "carga_dia",
        "pallets_origen": "preparados_noche",
        "num_pallets": num_pallets,
        "tiempo_por_pallet": tiempo_por_pallet,
        "cajas_pickeadas_detalle": pallet_data
    }
    
    centro.eventos.append(evento_dia)

def compilar_resultados_dia(centro_dia, estado_inicial, camiones_procesados, cfg_dia):
    """
    Compila los resultados finales del turno del día
    """
    # Determinar camiones que salen durante el día
    nueva_salida_camiones = []
    for evento in centro_dia.eventos:
        if evento.get("vuelta", 0) > 1:
            nueva_salida_camiones.append({
                "camion_id": evento["camion_id"],
                "vuelta_cargada": evento["vuelta"],
                "cajas_cargadas": evento["cajas_pre"],
                "hora_salida_dia": evento["fin_hhmm"],
                "origen": "pallets_preparados_noche"
            })
    
    # Generar cronograma formateado
    cronograma_formateado = formatear_cronograma_dia(centro_dia.eventos)
    
    resultado_dia = {
        "tipo_turno": "dia",
        "basado_en_noche": True,
        "turno_inicio": "08:00",
        "turno_fin": "23:59",
        "camiones_procesados": camiones_procesados,
        "vueltas_cargadas": len(estado_inicial.get("vueltas_pendientes", [])),
        "centro_eventos_dia": centro_dia.eventos,
        "cronograma_formateado": cronograma_formateado,
        "estado_inicial_usado": estado_inicial,
        "nueva_salida_camiones": nueva_salida_camiones,
        "configuracion_usada": cfg_dia
    }
    
    return resultado_dia