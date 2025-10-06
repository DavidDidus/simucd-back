from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.simulation_api import router as simulation_router

app = FastAPI(
    title="SimuCD - Simulador Centro de Distribución",
    description="API para simulación de operaciones del Centro de Distribución",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir router de simulación
app.include_router(simulation_router)

@app.get("/")
async def root():
    return {
        "message": "SimuCD API - Gemelo Digital Centro de Distribución",
        "version": "1.0.0",
        "endpoints": {
            "simulate": "/cd-operations/simulate",
            "status": "/cd-operations/status",
            "docs": "/docs",
            "health": "/health"
        }
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "simucd-api"}