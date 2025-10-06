from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

class ShiftConfiguration(BaseModel):
    """Configuración de un turno específico"""
    shift_type: str  # "night", "day", "weekend"
    enabled: bool = True
    total_cajas_facturadas: int
    cajas_para_pick: int
    config_overrides: Optional[Dict[str, Any]] = None

class CDOperationRequest(BaseModel):
    """Request para simulación completa de operaciones del CD"""
    
    # Simulaciones a ejecutar
    night_shift: Optional[ShiftConfiguration] = None
    day_shift: Optional[ShiftConfiguration] = None
    weekend_operations: Optional[ShiftConfiguration] = None
    
    # Configuración global
    simulation_period_days: int = Field(default=1, ge=1, le=30)
    seed: Optional[int] = Field(default=None, description="Semilla para reproducibilidad")
    global_config_overrides: Optional[Dict[str, Any]] = None
    
    # Opciones de análisis
    include_transitions: bool = Field(default=True, description="Incluir análisis de transiciones entre turnos")
    analyze_bottlenecks: bool = Field(default=True, description="Análisis detallado de cuellos de botella")
    
    model_config = {  # ← Cambiar de class Config a model_config
        "json_schema_extra": {  # ← Cambiar de schema_extra a json_schema_extra
            "example": {
                "night_shift": {
                    "shift_type": "night",
                    "enabled": True,
                    "total_cajas_facturadas": 25000,
                    "cajas_para_pick": 18000
                },
                "simulation_period_days": 1,
                "seed": 42
            }
        }
    }

class ShiftResult(BaseModel):
    """Resultado de un turno específico"""
    shift_type: str
    success: bool
    execution_time_seconds: float
    
    # Resultados operacionales
    total_rounds: int
    overrun_minutes: float
    boxes_processed: int
    pallets_processed: int
    
    # Métricas clave
    crane_utilization_pct: float
    time_efficiency_pct: float
    bottlenecks_count: int
    
    # Detalles (opcional, para no sobrecargar respuesta)
    detailed_metrics: Optional[Dict[str, Any]] = None

class CDOperationResponse(BaseModel):
    """Response completa de operaciones del CD"""
    
    # Información de ejecución
    execution_id: str
    timestamp: datetime
    total_execution_time_seconds: float
    
    # Parámetros de entrada
    input_params: CDOperationRequest
    
    # Resultados por turno
    shift_results: List[ShiftResult]
    
    # Análisis integrado
    overall_efficiency_pct: float
    total_boxes_processed: int
    total_overrun_minutes: float
    critical_bottlenecks: List[str]
    
    # Insights y recomendaciones
    performance_insights: List[str]
    optimization_recommendations: List[str]
    
    # Comparativas (si hay múltiples turnos)
    shift_comparison: Optional[Dict[str, Any]] = None