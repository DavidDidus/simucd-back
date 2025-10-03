# Simucd



## Estructura del Proyecto

```
simucd-back/
├── app/
│   └── simulations/
│       ├── night/               # Simulación nocturna principal
│       │   ├── __init__.py
│       │   ├── simulation.py    # Función principal de simulación
│       │   ├── config.py        # Configuración por defecto
│       │   ├── resources.py     # Modelado de recursos y procesos
│       │   ├── generators.py    # Generación de pallets y planificación
│       │   ├── metrics.py       # Cálculo de métricas (ICE, utilización)
│       │   └── utils.py         # Utilidades y helpers
│       └── Subestandar.py       # Simulación de productos subestándar (No terminado)
└── test/
    └── test_night_simulation.py # Test principal con análisis completo 
```

## Instalación

### Prerrequisitos

- **Python 3.8+**
- **pip** (gestor de paquetes de Python)

### Instalar dependencias

```bash
pip install simpy
```

**Nota**: SimPy es la única dependencia externa requerida. El resto del código utiliza bibliotecas estándar de Python (`random`, `statistics`, `collections`, etc.).

## Ejecución de la Simulación

### Método 1: Ejecutar el test completo (recomendado)

```bash
# Desde el directorio simucd-back
python test/test_night_simulation.py
```

Este comando ejecuta una simulación completa con análisis detallado y genera un reporte extenso con:
- Resumen general de tiempos y overrun
- Análisis detallado por vuelta
- Métricas ICE y utilización de recursos
- Timeline de operaciones
- Detección de cuellos de botella

