from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import simulation_api

app = FastAPI(title="SimuCD Backend", version="1.0.0")

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Ajusta según tu frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(simulation_api.router, prefix="/api", tags=["simulation"])

@app.get("/")
def read_root():
    return {"message": "SimuCD Backend API"}