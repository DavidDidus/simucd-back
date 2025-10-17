import numpy as np
from app.simulations.night.simulation import simular_turno_prioridad_rng
from app.simulations.night.config import DEFAULT_CONFIG

class SimulationService:
    
    def _convert_numpy_types(self, obj):
        """
        Convierte recursivamente tipos de NumPy a tipos nativos de Python
        """
        if obj is None:
            return None
        if isinstance(obj, (np.integer, np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, (np.floating, np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {str(key): self._convert_numpy_types(value) for key, value in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._convert_numpy_types(item) for item in obj]
        elif isinstance(obj, str):
            return obj
        elif isinstance(obj, (int, float, bool)):
            return obj
        # Para cualquier otro objeto, intentar convertir a string
        else:
            try:
                return str(obj)
            except:
                return None
    
    def run_night_simulation(
        self, 
        cajas_facturadas: int,
        cajas_piqueadas: int,
        pickers: int,
        grueros: int,
        chequeadores: int,
        parrilleros: int
    ):
        """
        Ejecuta la simulación de noche con los parámetros especificados
        """
        try:
            # Crear configuración personalizada basada en DEFAULT_CONFIG
            config = DEFAULT_CONFIG.copy()
            
            # Actualizar con los parámetros del usuario
            config.update({
                "cap_picker": pickers,
                "cap_gruero": grueros,
                "cap_chequeador": chequeadores,
                "cap_parrillero": parrilleros,
            })
            
            # Ejecutar simulación
            resultado = simular_turno_prioridad_rng(
                total_cajas_facturadas=cajas_facturadas,
                cajas_para_pick=cajas_piqueadas,
                cfg=config,
                seed=None
            )
            
            # Convertir tipos de NumPy a tipos nativos de Python
            resultado_serializable = self._convert_numpy_types(resultado)
            
            return resultado_serializable
            
        except Exception as e:
            raise Exception(f"Error al ejecutar simulación: {str(e)}")