# test_single_detailed.py
"""
Test único con análisis completo y detallado de la simulación nocturna
Ejecuta una sola simulación y muestra toda la información disponible
"""

import sys
import os
import time
from datetime import datetime

# Agregar el directorio app al path si no está
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.simulations.night import simular_turno_prioridad_rng, DEFAULT_CONFIG

def formato_tiempo(minutos):
    """Convierte minutos a formato HH:MM"""
    horas = int(minutos // 60)
    mins = int(minutos % 60)
    return f"{horas:02d}:{mins:02d}"

def main():
    """Test único con análisis completo"""
    print(f"🚀 SIMULACIÓN NOCTURNA - ANÁLISIS COMPLETO")
    print(f"Ejecutado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")
    
    # Parámetros de la simulación
    total_cajas_facturadas = 14680
    cajas_para_pick = 13583
    seed = 42  # Para reproducibilidad
    
    print(f"📋 PARÁMETROS DE ENTRADA:")
    print(f"   Cajas totales facturadas: {total_cajas_facturadas:,}")
    print(f"   Cajas para pick (mixtas): {cajas_para_pick:,}")
    print(f"   Cajas completas (directas): {total_cajas_facturadas - cajas_para_pick:,}")
    print(f"   Semilla: {seed}")
    print(f"   Configuración: DEFAULT_CONFIG")
    
    # Ejecutar simulación
    print(f"\n⚡ EJECUTANDO SIMULACIÓN...")
    inicio = time.time()
    
    resultado = simular_turno_prioridad_rng(
        total_cajas_facturadas=total_cajas_facturadas,
        cajas_para_pick=cajas_para_pick,
        cfg=DEFAULT_CONFIG,
        seed=seed
    )
    
    fin = time.time()
    tiempo_ejecucion = fin - inicio
    print(f"   ✅ Completado en {tiempo_ejecucion:.2f} segundos")
    
    # ================== ANÁLISIS DETALLADO ==================
    
    # 1. RESUMEN GENERAL
    print(f"\n🎯 RESUMEN GENERAL")
    print(f"{'─'*60}")
    entradas = resultado['entradas_cajas']
    print(f"Cajas procesadas:")
    print(f"   • Total facturadas: {entradas['total_cajas_facturadas']:,}")
    print(f"   • Para pick (mixtas): {entradas['cajas_para_pick']:,}")
    print(f"   • Completas (directas): {entradas['cajas_completas']:,}")
    print(f"   • % Mixtas: {(entradas['cajas_para_pick'] / entradas['total_cajas_facturadas'] * 100):.1f}%")
    
    print(f"\nPallets generados:")
    pallets = resultado['pallets_pre']
    print(f"   • Total: {resultado['pallets_pre_total']}")
    print(f"   • Mixtos: {pallets['pallets_mixtos']}")
    print(f"   • Completos: {pallets['pallets_completos']}")
    
   # print(f"\nPlanificación:")
    #print(f"   • Vueltas: {resultado['vueltas']}")
    
    # 2. TIEMPOS DEL TURNO
    print(f"\n⏰ TIEMPOS DEL TURNO")
    print(f"{'─'*60}")
    print(f"Inicio del turno: {resultado['turno_inicio']}")
    print(f"Fin nominal (8h): {resultado['turno_fin_nominal']}")
    print(f"Fin real: {resultado['turno_fin_real']}")
    
    overrun = resultado['overrun_total_min']
    if overrun > 0:
        print(f"⚠️  OVERRUN: {overrun:.1f} minutos ({formato_tiempo(overrun)})")
        print(f"   Exceso sobre turno nominal: {(overrun/480*100):.1f}%")
    else:
        print(f"✅ Sin overrun - Terminó dentro del turno")
    
    # 3. ANÁLISIS DETALLADO POR VUELTA
    print(f"\n🔄 ANÁLISIS DETALLADO POR VUELTA")
    print(f"{'─'*60}")

    
    for i, vuelta in enumerate(resultado['resumen_vueltas']):
        v_num = vuelta['vuelta']
        modo = vuelta['modo'].upper()
        
        print(f"\n   🎯 VUELTA {v_num} - {modo}")
        print(f"   {'┄'*45}")
        
        # Información básica
        print(f"   Camiones participantes: {vuelta['camiones_en_vuelta']}")
        print(f"   Pallets asignados: {vuelta['pre_quemados_pallets']}")
        print(f"   Cajas procesadas: {vuelta['pre_quemados_cajas']:,}")
        
        # Timeline detallado
        print(f"   Timeline:")
        print(f"      Inicio: {vuelta['inicio_hhmm']}")
        if vuelta['pick_fin_hhmm']:
            print(f"      Fin PICK: {vuelta['pick_fin_hhmm']} ⭐")
        print(f"      Fin operativo: {vuelta['fin_operativo_hhmm']}")
        print(f"      Fin oficial: {vuelta['fin_hhmm']}")
        
        # Duraciones
        print(f"   Duraciones:")
        print(f"      Total oficial: {vuelta['duracion_vuelta_min']:.1f} min")
        print(f"      Operativa: {vuelta['duracion_operativa_min']:.1f} min")
        
        # Overrun específico
        if vuelta['overrun_min'] > 0:
            print(f"      ⚠️  Overrun: {vuelta['overrun_min']:.1f} min")
        else:
            print(f"      ✅ Sin overrun")
    
    print(f"\n🚛 DESGLOSE DETALLADO POR CAMIÓN")
    print(f"{'='*80}")
    
    # Obtener información de todos los camiones de todas las vueltas
    if 'centro_eventos' in resultado:
        eventos_camiones = resultado['centro_eventos']
        
        # Agrupar por vuelta
        camiones_por_vuelta = {}
        for evento in eventos_camiones:
            vuelta = evento['vuelta']
            if vuelta not in camiones_por_vuelta:
                camiones_por_vuelta[vuelta] = []
            camiones_por_vuelta[vuelta].append(evento)
        
        total_camiones = 0
        total_pallets_todos = 0
        total_cajas_todas = 0
        
        for vuelta in sorted(camiones_por_vuelta.keys()):
            camiones = camiones_por_vuelta[vuelta]
            modo = "CARGA" if vuelta == 1 else "STAGING"
            
            print(f"\n🔄 VUELTA {vuelta} - {modo}")
            print(f"{'─'*70}")
            print(f"Camiones en esta vuelta: {len(camiones)}")

             # Encabezados de tabla
            print(f"\n{'ID':>3} │ {'Pallets':>8} │ {'Cajas':>8} │ {'Mix/Comp':>8} │ {'Fusión':>7} │ {'Tiempo':>8}")
            print(f"{'───':>3}─┼─{'────────':>8}─┼─{'────────':>8}─┼─{'────────':>8}─┼─{'───────':>7}─┼─{'────────':>8}")
          
            total_pallets_vuelta = 0
            total_cajas_vuelta = 0
            total_fusionados_vuelta = 0
            
            for camion in sorted(camiones, key=lambda x: x['camion_id']):
                id_cam = camion['camion_id']
                pre_pallets = camion['pre_asignados']
                post_pallets = camion.get('post_cargados', pre_pallets)
                cajas_total = camion['cajas_pre']
                fusionados = camion.get('fusionados', 0)
                tiempo_min = camion['tiempo_min']
                
                # Determinar tipo predominante
                cajas_mixto = camion.get('cajas_pick_mixto', 0)
                cajas_completo = cajas_total - cajas_mixto
                tipo = f"{cajas_mixto}M/{cajas_completo}C"
                
                # Para vuelta 1, mostrar fusionados
                if vuelta == 1:
                     fusion_info = f"{fusionados:>3}"
                else:
                     fusion_info = "─"
                
                print(f"{id_cam:>3} │ {pre_pallets:>3}→{post_pallets:>3} │ {cajas_total:>8,} │ {tipo:>8} │ {fusion_info:>7} │ {tiempo_min:>6.1f}m")
                
                total_pallets_vuelta += post_pallets
                total_cajas_vuelta += cajas_total
                total_fusionados_vuelta += fusionados
                total_camiones += 1
            
            # Totales por vuelta
            print(f"{'───':>3}─┼─{'────────':>8}─┼─{'────────':>8}─┼─{'────────':>8}─┼─{'───────':>7}─┼─{'────────':>8}")
            fusion_total = f"{total_fusionados_vuelta}" if vuelta == 1 else "─"
            print(f"{'TOT':>3} │ {total_pallets_vuelta:>8} │ {total_cajas_vuelta:>8,} │ {'':>8} │ {fusion_total:>7} │ {'':>8}")
            
            total_pallets_todos += total_pallets_vuelta
            total_cajas_todas += total_cajas_vuelta
            
             # Estadísticas de la vuelta
            #if len(camiones) > 0:
                #promedio_pallets = total_pallets_vuelta / len(camiones)
                #promedio_cajas = total_cajas_vuelta / len(camiones)
                #promedio_tiempo = sum(c['tiempo_min'] for c in camiones) / len(camiones)
                
                #print(f"\n📊 Estadísticas Vuelta {vuelta}:")
               # print(f"   • Promedio pallets/camión: {promedio_pallets:.1f}")
              #  print(f"   • Promedio cajas/camión: {promedio_cajas:,.0f}")
             #   print(f"   • Tiempo promedio: {promedio_tiempo:.1f} min")
                
            #    if vuelta == 1 and total_fusionados_vuelta > 0:
           #         tasa_fusion = (total_fusionados_vuelta / sum(c['pre_asignados'] for c in camiones)) * 100
          #          print(f"   • Tasa de fusión: {tasa_fusion:.1f}%")
         # # ================== RESUMEN GENERAL DE CAMIONES ==================
        
        #print(f"\n📈 RESUMEN GENERAL DE TODOS LOS CAMIONES")
        #print(f"{'='*70}")
       # print(f"Total camiones procesados: {total_camiones}")
      #  print(f"Total pallets cargados: {total_pallets_todos:,}")
      #  print(f"Total cajas transportadas: {total_cajas_todas:,}")
        
      #  if total_camiones > 0:
      #      print(f"Promedio pallets por camión: {total_pallets_todos / total_camiones:.1f}")
     #       print(f"Promedio cajas por camión: {total_cajas_todas / total_camiones:,.0f}")
        
        # ================== ANÁLISIS DE CAPACIDADES ==================
        
      #  print(f"\n📦 ANÁLISIS DE CAPACIDADES UTILIZADAS")
      #  print(f"{'─'*70}")
        
        # Buscar información de capacidades si está disponible
       # capacidades_utilizadas = []
       # for evento in eventos_camiones:
       #     if 'capacidad_pallets_usada' in evento or 'capacidad_cajas_usada' in evento:
       #         capacidades_utilizadas.append({
       #             'camion': evento['camion'],
       #             'vuelta': evento['vuelta'],
       #             'pallets_cap': evento.get('capacidad_pallets_usada', 'N/A'),
       #             'cajas_cap': evento.get('capacidad_cajas_usada', 'N/A'),
       #             'pallets_real': evento.get('post_cargados', evento['pre_asignados']),
       #             'cajas_real': evento['cajas_pre']
       #         })
       # if capacidades_utilizadas:
      #      print(f"{'ID':>3} │ {'Vuelta':>6} │ {'Cap.Pal':>7} │ {'Real.Pal':>8} │ {'Cap.Cajas':>9} │ {'Real.Cajas':>10} │ {'Util%':>6}")
     #       print(f"{'───':>3}─┼─{'──────':>6}─┼─{'───────':>7}─┼─{'────────':>8}─┼─{'─────────':>9}─┼─{'──────────':>10}─┼─{'──────':>6}")
    #        
    #        for cap in sorted(capacidades_utilizadas, key=lambda x: (x['vuelta'], x['camion'])):
    #            util_pal = (cap['pallets_real'] / cap['pallets_cap'] * 100) if cap['pallets_cap'] != 'N/A' else 0
    #            util_cajas = (cap['cajas_real'] / cap['cajas_cap'] * 100) if cap['cajas_cap'] != 'N/A' else 0
    #            util_prom = (util_pal + util_cajas) / 2 if util_pal > 0 and util_cajas > 0 else max(util_pal, util_cajas)
                
    #            print(f"{cap['camion']:>3} │ {cap['vuelta']:>6} │ {cap['pallets_cap']:>7} │ {cap['pallets_real']:>8} │ {cap['cajas_cap']:>9} │ {cap['cajas_real']:>10,} │ {util_prom:>5.1f}%")
        
        # ================== TOP CAMIONES ==================
        
    #    print(f"\n🏆 TOP CAMIONES")
    #    print(f"{'─'*50}")
        
        # Top por cajas
    #    camiones_ordenados_cajas = sorted(eventos_camiones, key=lambda x: x['cajas_pre'], reverse=True)[:5]
    #    print(f"🥇 TOP 5 - MÁS CAJAS:")
    #    for i, cam in enumerate(camiones_ordenados_cajas, 1):
    #        print(f"   {i}. Camión {cam['camion']} (V{cam['vuelta']}): {cam['cajas_pre']:,} cajas")
        
         # Top por pallets
    #    camiones_ordenados_pallets = sorted(eventos_camiones, key=lambda x: x.get('post_cargados', x['pre_asignados']), reverse=True)[:5]
    #    print(f"\n📦 TOP 5 - MÁS PALLETS:")
    #    for i, cam in enumerate(camiones_ordenados_pallets, 1):
    #        pallets = cam.get('post_cargados', cam['pre_asignados'])
    #        print(f"   {i}. Camión {cam['camion']} (V{cam['vuelta']}): {pallets} pallets")
        
        # Top por tiempo
    #    camiones_ordenados_tiempo = sorted(eventos_camiones, key=lambda x: x['tiempo_min'], reverse=True)[:5]
    #    print(f"\n⏱️  TOP 5 - MÁS TIEMPO:")
    #    for i, cam in enumerate(camiones_ordenados_tiempo, 1):
    #        print(f"   {i}. Camión {cam['camion']} (V{cam['vuelta']}): {cam['tiempo_min']:.1f} min")
        
    #else:
    #    print(f"⚠️  No se encontró información detallada de camiones en el resultado")
    #    print(f"   Verifica que 'centro_eventos' esté incluido en el resultado de la simulación")

            
        
        
        # Métricas específicas por tipo
        #if v_num == 1:  # Vuelta 1 - CARGA
        #    print(f"   Métricas de carga:")
        #    print(f"      Pallets cargados final: {vuelta['post_cargados_pallets']}")
        #    print(f"      Pallets fusionados: {vuelta['fusionados']}")
        #    if vuelta['pre_quemados_pallets'] > 0:
        #        eficiencia = (vuelta['post_cargados_pallets'] / vuelta['pre_quemados_pallets']) * 100
        #        print(f"      Eficiencia de carga: {eficiencia:.1f}%")
        #        if vuelta['fusionados'] > 0:
        #            print(f"      Tasa de fusión: {(vuelta['fusionados'] / vuelta['pre_quemados_pallets'] * 100):.1f}%")
        #else:  # Vueltas 2+ - STAGING
        #    print(f"   Modo staging - Solo preparación para despacho")
        
    # 4. ICE (ÍNDICE DE CAPACIDAD EFECTIVA)
    #print(f"\n📈 ICE - ÍNDICE DE CAPACIDAD EFECTIVA (MIXTAS)")
    #print(f"{'─'*60}")
    ice = resultado['ice_mixto']
    #print(f"Cajas mixtas pickeadas: {ice['total_cajas_pickeadas_mixtas']:,}")
    #print(f"Pickers disponibles: {ice['pickers']}")
    #print(f"Horas efectivas configuradas: {ice['horas_efectivas']}")
    
    if ice['valor']:
        print(f"ICE CALCULADO: {ice['valor']:.2f} cajas/picker/hora")
        
        # Interpretación del ICE
        #if ice['valor'] < 50:
        #    print(f"   📉 ICE BAJO - Posible sub-utilización de pickers")
        #elif ice['valor'] < 80:
        #    print(f"   📊 ICE NORMAL - Operación dentro de parámetros estándar")
        #elif ice['valor'] < 120:
        #    print(f"   📈 ICE ALTO - Alta eficiencia de picking")
        #else:
        #    print(f"   🚀 ICE MUY ALTO - Eficiencia excepcional")
    #else:
        #print(f"ICE: No calculable")
    
    # 5. ANÁLISIS COMPLETO DE GRÚA
    #print(f"\n🏗️  ANÁLISIS COMPLETO DE GRÚA")
    #print(f"{'─'*60}")
    
    #grua = resultado['grua']
    #overall = grua['overall']
    
    #print(f"📊 MÉTRICAS GENERALES:")
    #print(f"   Operaciones totales: {overall['ops']}")
    #print(f"   Tiempo total ocupado: {overall['total_hold_min']:.1f} min ({formato_tiempo(overall['total_hold_min'])})")
    #print(f"   Tiempo total de espera: {overall['total_wait_min']:.1f} min ({formato_tiempo(overall['total_wait_min'])})")
    #print(f"   Espera promedio por operación: {overall['mean_wait_min']:.2f} min")
    #print(f"   UTILIZACIÓN: {overall['utilizacion_prom']:.1%}")
    
    # Interpretación de utilización
    #util = overall['utilizacion_prom']
    #if util < 0.6:
    #    print(f"      📉 Utilización baja - Capacidad de grúa sobrada")
    #elif util < 0.8:
    #    print(f"      📊 Utilización normal - Operación eficiente")
    #elif util < 0.9:
    #    print(f"      📈 Utilización alta - Cerca del límite de capacidad")
    #else:
    #    print(f"      🚨 UTILIZACIÓN CRÍTICA - Posible cuello de botella")
    
    # Análisis por vuelta
    #print(f"\n📊 GRÚA POR VUELTA:")
    #for v in grua['por_vuelta']:
    #    print(f"   Vuelta {v['vuelta']}:")
    #    print(f"      Operaciones: {v['ops']}")
    #    print(f"      Espera promedio: {v['mean_wait_min']:.2f} min")
    #    print(f"      Espera máxima: {v['max_wait_min']:.2f} min")
    #    print(f"      Tiempo ocupado: {v['total_hold_min']:.1f} min")
    
    # Análisis por tipo de operación
    #print(f"\n📊 GRÚA POR TIPO DE OPERACIÓN:")
    #for label, data in sorted(grua['por_label'].items()):
    #    print(f"   {label}:")
    #    print(f"      Operaciones: {data['ops']}")
    #    print(f"      Espera promedio: {data['mean_wait_min']:.2f} min")
    #    print(f"      Tiempo total: {data['total_hold_min']:.1f} min")
    #    print(f"      Tiempo promedio por operación: {data['mean_hold_min']:.2f} min")
    
    # 6. DETECCIÓN DE CUELLOS DE BOTELLA
    #print(f"\n🚧 ANÁLISIS DE CUELLOS DE BOTELLA")
    #print(f"{'─'*60}")
    
    # Operación con mayor espera
    #if grua['por_label']:
    #    max_wait_op = max(grua['por_label'].items(), key=lambda x: x[1]['mean_wait_min'])
    #    print(f"Operación con mayor espera: {max_wait_op[0]}")
    #    print(f"   Espera promedio: {max_wait_op[1]['mean_wait_min']:.2f} min")
    #    if max_wait_op[1]['mean_wait_min'] > 3:
    #        print(f"   ⚠️  CUELLO DE BOTELLA DETECTADO")
    
    # Vuelta más lenta
    #vuelta_lenta = max(resultado['resumen_vueltas'], key=lambda x: x['duracion_vuelta_min'])
    #print(f"Vuelta más lenta: V{vuelta_lenta['vuelta']}")
    #print(f"   Duración: {vuelta_lenta['duracion_vuelta_min']:.1f} min")
    
    # Análisis de overrun por vuelta
    #overruns = [v for v in resultado['resumen_vueltas'] if v['overrun_min'] > 0]
    #if overruns:
    #    print(f"Vueltas con overrun: {len(overruns)}/{len(resultado['resumen_vueltas'])}")
    #    for v in overruns:
    #        print(f"   V{v['vuelta']}: +{v['overrun_min']:.1f} min sobre turno nominal")
    #else:
    #    print(f"✅ Todas las vueltas terminaron dentro del turno nominal")
    
    # 7. RESUMEN DE EFICIENCIAS
    #print(f"\n📊 RESUMEN DE EFICIENCIAS")
    #print(f"{'─'*60}")
    
    # Eficiencia temporal general
    #tiempo_nominal = 480  # 8 horas en minutos
    #tiempo_real_max = max((v['duracion_vuelta_min'] + v.get('inicio_min', 0)) for v in resultado['resumen_vueltas']) if resultado['resumen_vueltas'] else 0
    #if tiempo_real_max > 0:
    #    eficiencia_temporal = min((tiempo_nominal / tiempo_real_max) * 100, 100)
    #    print(f"Eficiencia temporal del turno: {eficiencia_temporal:.1f}%")
    
    # Eficiencia de fusión (solo V1)
    #v1 = next((v for v in resultado['resumen_vueltas'] if v['vuelta'] == 1), None)
    #if v1 and v1['pre_quemados_pallets'] > 0:
    #    eficiencia_fusion = (v1['post_cargados_pallets'] / v1['pre_quemados_pallets']) * 100
    #    print(f"Eficiencia de fusión V1: {eficiencia_fusion:.1f}%")
    #    print(f"Tasa de reducción: {100 - eficiencia_fusion:.1f}%")
    
    # Eficiencias de recursos
    #print(f"Utilización de grúa: {overall['utilizacion_prom']:.1%}")
    #if ice['valor']:
        #print(f"Productividad picking (ICE): {ice['valor']:.1f} cajas/picker/hora")
    
    # 8. CONFIGURACIÓN UTILIZADA
    print(f"\n⚙️  CONFIGURACIÓN UTILIZADA")
    print(f"{'─'*60}")
    cfg = DEFAULT_CONFIG
    print(f"Recursos:")
    print(f"   Camiones: {cfg['camiones']}")
    print(f"   Capacidad grúa: {cfg['cap_gruero']}")
    print(f"   Pickers: {cfg['cap_picker']}")
    print(f"   Chequeadores: {cfg['cap_chequeador']}")
    print(f"   Patio (slots): {cfg['cap_patio']}")
    
    #print(f"Parámetros pallets:")
    #print(f"   Target por vuelta: {cfg['target_pallets_por_vuelta']}")
    #print(f"   Capacidad por camión: {cfg['capacidad_pallets_camion']}")
    #print(f"   Cajas mixto: {cfg['cajas_mixto']}")
    #print(f"   Cajas completo: {cfg['cajas_completo']}")
    
    # 9. CONCLUSIONES Y RECOMENDACIONES
    #print(f"\n💡 CONCLUSIONES Y RECOMENDACIONES")
    #print(f"{'─'*60}")
    
    # Análisis automático de resultados
    #if resultado['overrun_total_min'] == 0:
    #    print(f"✅ EXCELENTE: Turno completado dentro del tiempo nominal")
    #elif resultado['overrun_total_min'] < 30:
    #   print(f"✅ BUENO: Overrun mínimo ({resultado['overrun_total_min']:.1f} min)")
    #elif resultado['overrun_total_min'] < 60:
    #    print(f"⚠️  REGULAR: Overrun moderado ({resultado['overrun_total_min']:.1f} min)")
    #else:
    #    print(f"🚨 CRÍTICO: Overrun significativo ({resultado['overrun_total_min']:.1f} min)")
    
    #if overall['utilizacion_prom'] > 0.85:
    #    print(f"⚠️  Grúa en alta utilización - Considerar capacidad adicional")
    #elif overall['utilizacion_prom'] < 0.6:
    #    print(f"💡 Grúa sub-utilizada - Oportunidad de optimización")
    
    #if ice['valor'] and ice['valor'] < 60:
    #    print(f"💡 ICE bajo - Revisar eficiencia de picking")
    
    print(f"\n{'='*80}")
    print(f"🎉 ANÁLISIS COMPLETO TERMINADO")
    print(f"Tiempo total de ejecución: {tiempo_ejecucion:.2f} segundos")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()