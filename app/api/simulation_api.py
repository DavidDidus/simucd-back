from fastapi import APIRouter, HTTPException, Depends
from ..models.base import CDOperationRequest, CDOperationResponse
from ..services.simulation_service import CDOperationsService

router = APIRouter(prefix="/cd-operations", tags=["cd-operations"])

def get_cd_operations_service() -> CDOperationsService:
    return CDOperationsService()

@router.post("/simulate", response_model=CDOperationResponse)
async def simulate_cd_operations(
    request: CDOperationRequest,
    service: CDOperationsService = Depends(get_cd_operations_service)
):
    """
    Ejecuta simulación integrada de operaciones del Centro de Distribución
    
    Permite simular múltiples turnos en conjunto:
    - Turno nocturno (picking intensivo)
    - Turno diurno (despacho y recepción)
    - Operaciones de fin de semana
    
    Proporciona análisis integrado y comparativo entre turnos.
    """
    try:
        return await service.run_cd_simulation(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en simulación: {str(e)}")

@router.get("/status")
async def get_operations_status(
    service: CDOperationsService = Depends(get_cd_operations_service)
):
    """Estado de simulaciones de operaciones en progreso"""
    return service.running_simulations