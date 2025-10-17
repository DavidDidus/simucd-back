from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
import numpy as np
import json
from app.services.simulation_service import SimulationService

router = APIRouter()
simulation_service = SimulationService()

class NumpyEncoder(json.JSONEncoder):
    """Encoder personalizado para tipos de NumPy y otros objetos complejos"""
    def default(self, obj):
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        if isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, bytes):
            return obj.decode('utf-8')
        # Para objetos con __dict__
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)

class NightSimulationRequest(BaseModel):
    cajas_facturadas: int = Field(..., alias="Cajas facturadas", gt=0)
    cajas_piqueadas: int = Field(..., alias="Cajas piqueadas", ge=0)
    pickers: int = Field(..., alias="Pickers", gt=0)
    grueros: int = Field(..., alias="Grueros", gt=0)
    chequeadores: int = Field(..., alias="Chequeadores", gt=0)
    parrilleros: int = Field(..., alias="parrilleros", gt=0)

    class Config:
        populate_by_name = True

    @validator('cajas_piqueadas')
    def validate_cajas_piqueadas(cls, v, values):
        if 'cajas_facturadas' in values and v > values['cajas_facturadas']:
            raise ValueError('Las cajas piqueadas no pueden ser mayores que las facturadas')
        return v

@router.post("/simulate")
async def run_night_simulation(request: NightSimulationRequest):
    """
    Ejecuta la simulación de noche con los parámetros especificados
    """
    try:
        result = simulation_service.run_night_simulation(
            cajas_facturadas=request.cajas_facturadas,
            cajas_piqueadas=request.cajas_piqueadas,
            pickers=request.pickers,
            grueros=request.grueros,
            chequeadores=request.chequeadores,
            parrilleros=request.parrilleros
        )
        
        response_data = {
            "success": True,
            "data": result,
            "message": "Simulación ejecutada exitosamente"
        }
        
        # Serializar con el encoder personalizado
        json_str = json.dumps(response_data, cls=NumpyEncoder, ensure_ascii=False, default=str)
        
        return JSONResponse(
            content=json.loads(json_str),
            status_code=200
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        error_detail = {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        raise HTTPException(status_code=500, detail=f"Error en la simulación: {str(e)}")

@router.get("/test")
async def test_endpoint():
    """Endpoint de prueba"""
    return {"status": "ok", "message": "API funcionando correctamente"}