from typing import Dict, Any, List, Optional
import time
import uuid
from datetime import datetime

from ..models.base import CDOperationRequest, CDOperationResponse, ShiftResult, ShiftConfiguration
from ..simulations.night import simular_turno_prioridad_rng, DEFAULT_CONFIG

class CDOperationsService:
    """Servicio para simulaciones integradas del Centro de Distribución"""
    
    def __init__(self):
        self.running_simulations: Dict[str, Dict[str, Any]] = {}
    
    async def run_cd_simulation(self, request: CDOperationRequest) -> CDOperationResponse:
        """Ejecuta simulación completa de operaciones del CD"""
        
        # Generar ID único
        execution_id = str(uuid.uuid4())
        timestamp = datetime.now()
        
        try:
            # Registrar simulación
            self.running_simulations[execution_id] = {
                "status": "running",
                "start_time": timestamp,
                "shifts_planned": self._count_enabled_shifts(request)
            }
            
            print(f"🚀 Iniciando simulación CD {execution_id}")
            
            start_time = time.time()
            shift_results = []
            
            # Ejecutar cada turno habilitado
            if request.night_shift and request.night_shift.enabled:
                print(f"   Ejecutando turno nocturno...")
                result = await self._run_shift_simulation(request.night_shift, request.global_config_overrides, request.seed)
                shift_results.append(result)
            
            if request.day_shift and request.day_shift.enabled:
                print(f"   Ejecutando turno diurno...")
                result = await self._run_shift_simulation(request.day_shift, request.global_config_overrides, request.seed)
                shift_results.append(result)
            
            if request.weekend_operations and request.weekend_operations.enabled:
                print(f"   Ejecutando operaciones fin de semana...")
                result = await self._run_shift_simulation(request.weekend_operations, request.global_config_overrides, request.seed)
                shift_results.append(result)
            
            total_execution_time = time.time() - start_time
            
            # Análisis integrado
            response = self._build_integrated_response(
                execution_id, timestamp, total_execution_time, 
                request, shift_results
            )
            
            # Cleanup
            del self.running_simulations[execution_id]
            
            print(f"✅ Simulación CD {execution_id} completada en {total_execution_time:.2f}s")
            
            return response
            
        except Exception as e:
            if execution_id in self.running_simulations:
                del self.running_simulations[execution_id]
            print(f"❌ Error en simulación {execution_id}: {str(e)}")
            raise e
    
    async def _run_shift_simulation(
        self, 
        shift_config: ShiftConfiguration, 
        global_overrides: Optional[Dict[str, Any]], 
        seed: Optional[int]
    ) -> ShiftResult:
        """Ejecuta simulación de un turno específico"""
        
        start_time = time.time()
        
        # Preparar configuración combinada
        config = DEFAULT_CONFIG.copy()
        if global_overrides:
            config.update(global_overrides)
        if shift_config.config_overrides:
            config.update(shift_config.config_overrides)
        
        # Ejecutar simulación específica del turno
        if shift_config.shift_type == "night":
            raw_result = simular_turno_prioridad_rng(
                total_cajas_facturadas=shift_config.total_cajas_facturadas,
                cajas_para_pick=shift_config.cajas_para_pick,
                cfg=config,
                seed=seed
            )
        else:
            # Por ahora solo nocturno, después agregar otros
            raise ValueError(f"Tipo de turno no implementado aún: {shift_config.shift_type}")
        
        execution_time = time.time() - start_time
        
        # Convertir a resultado estándar
        return ShiftResult(
            shift_type=shift_config.shift_type,
            success=True,
            execution_time_seconds=execution_time,
            total_rounds=raw_result.get('vueltas', 0),
            overrun_minutes=raw_result.get('overrun_total_min', 0),
            boxes_processed=shift_config.total_cajas_facturadas,
            pallets_processed=raw_result.get('pallets_pre_total', 0),
            crane_utilization_pct=raw_result.get('grua', {}).get('overall', {}).get('utilizacion_prom', 0) * 100,
            time_efficiency_pct=self._calculate_time_efficiency(raw_result.get('overrun_total_min', 0)),
            bottlenecks_count=len(self._analyze_bottlenecks(raw_result)),
            detailed_metrics=raw_result
        )
    
    def _build_integrated_response(
        self,
        execution_id: str,
        timestamp: datetime,
        total_execution_time: float,
        request: CDOperationRequest,
        shift_results: List[ShiftResult]
    ) -> CDOperationResponse:
        """Construye respuesta integrada con análisis comparativo"""
        
        # Métricas agregadas
        total_boxes = sum(r.boxes_processed for r in shift_results)
        total_overrun = sum(r.overrun_minutes for r in shift_results)
        avg_efficiency = sum(r.time_efficiency_pct for r in shift_results) / len(shift_results) if shift_results else 0
        
        # Análisis de cuellos de botella críticos
        critical_bottlenecks = []
        for result in shift_results:
            if result.crane_utilization_pct > 90:
                critical_bottlenecks.append(f"Grúa saturada en turno {result.shift_type}")
            if result.overrun_minutes > 60:
                critical_bottlenecks.append(f"Overrun crítico en turno {result.shift_type}")
        
        # Insights y recomendaciones
        insights = self._generate_integrated_insights(shift_results)
        recommendations = self._generate_optimization_recommendations(shift_results)
        
        # Comparativa entre turnos (si hay más de uno)
        comparison = None
        if len(shift_results) > 1:
            comparison = {
                "most_efficient_shift": max(shift_results, key=lambda r: r.time_efficiency_pct).shift_type,
                "most_problematic_shift": max(shift_results, key=lambda r: r.overrun_minutes).shift_type,
                "efficiency_variance": max(r.time_efficiency_pct for r in shift_results) - min(r.time_efficiency_pct for r in shift_results)
            }
        
        return CDOperationResponse(
            execution_id=execution_id,
            timestamp=timestamp,
            total_execution_time_seconds=total_execution_time,
            input_params=request,
            shift_results=shift_results,
            overall_efficiency_pct=avg_efficiency,
            total_boxes_processed=total_boxes,
            total_overrun_minutes=total_overrun,
            critical_bottlenecks=critical_bottlenecks,
            performance_insights=insights,
            optimization_recommendations=recommendations,
            shift_comparison=comparison
        )
    
    def _count_enabled_shifts(self, request: CDOperationRequest) -> int:
        """Cuenta turnos habilitados"""
        count = 0
        if request.night_shift and request.night_shift.enabled:
            count += 1
        if request.day_shift and request.day_shift.enabled:
            count += 1
        if request.weekend_operations and request.weekend_operations.enabled:
            count += 1
        return count
    
    def _calculate_time_efficiency(self, overrun_minutes: float) -> float:
        """Calcula eficiencia temporal"""
        nominal_minutes = 480  # 8 horas
        return min(100, (nominal_minutes / (nominal_minutes + overrun_minutes)) * 100)
    
    def _analyze_bottlenecks(self, raw_result: Dict[str, Any]) -> List[str]:
        """Análisis simple de cuellos de botella"""
        bottlenecks = []
        crane_util = raw_result.get('grua', {}).get('overall', {}).get('utilizacion_prom', 0)
        if crane_util > 0.85:
            bottlenecks.append("crane_saturation")
        return bottlenecks
    
    def _generate_integrated_insights(self, shift_results: List[ShiftResult]) -> List[str]:
        """Genera insights integrados"""
        insights = []
        
        if len(shift_results) == 1:
            result = shift_results[0]
            if result.time_efficiency_pct > 95:
                insights.append(f"Turno {result.shift_type} operando con alta eficiencia")
            elif result.time_efficiency_pct < 80:
                insights.append(f"Turno {result.shift_type} con oportunidades de mejora")
        
        if len(shift_results) > 1:
            efficiencies = [r.time_efficiency_pct for r in shift_results]
            if max(efficiencies) - min(efficiencies) > 20:
                insights.append("Alta variabilidad de eficiencia entre turnos")
        
        total_overrun = sum(r.overrun_minutes for r in shift_results)
        if total_overrun > 120:
            insights.append("Overrun acumulado significativo - revisar planificación")
        
        return insights
    
    def _generate_optimization_recommendations(self, shift_results: List[ShiftResult]) -> List[str]:
        """Genera recomendaciones de optimización"""
        recommendations = []
        
        high_util_shifts = [r for r in shift_results if r.crane_utilization_pct > 85]
        if high_util_shifts:
            recommendations.append("Considerar recursos adicionales de grúa en turnos de alta utilización")
        
        high_overrun_shifts = [r for r in shift_results if r.overrun_minutes > 60]
        if high_overrun_shifts:
            recommendations.append("Revisar planificación de volumen en turnos con overrun alto")
        
        return recommendations