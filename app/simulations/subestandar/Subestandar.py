import simpy
import random

# ------------------------------
# Parámetros del modelo
# ------------------------------
HORAS_TURNO = 8
TURNO = HORAS_TURNO * 60  # 480 minutos
DIAS = 10
CAJAS_POR_PALLET = 40

# Llegada de pallets
PALLETS_POR_DIA = 15
CAJAS_POR_PALLET_ENTRADA = 10  # promedio

# Tiempos (en minutos)
def t_acomodo_pallet(): return 2  # fijo por pallet
def t_proceso_caja(): return random.uniform(2, 3)  # material + clasificación
def t_armado_caja(): return random.uniform(2, 3)
T_POSICIONAR_PALLET = 5
T_GRUERO = 5

# Categorías
CATEGORIAS = ["gaseosa", "cerveza", "vino/destilado"]
PROB = [0.7, 0.25, 0.05]

# ------------------------------
# Variables globales
# ------------------------------
pallets = {cat: 0 for cat in CATEGORIAS}
cajas_en_pallet = {cat: 0 for cat in CATEGORIAS}

# ------------------------------
# Procesos
# ------------------------------
def proceso_pallet(env, nombre, trabajador, gruero):
    # Acomodo del pallet
    with trabajador.request() as req:
        yield req
        yield env.timeout(t_acomodo_pallet())
        print(f"[{env.now:.1f}] {nombre} acomodado en área de subestandar")

    # Procesar cajas del pallet
    for j in range(CAJAS_POR_PALLET_ENTRADA):
        yield env.process(proceso_caja(env, f"{nombre}-Caja{j+1}", trabajador, gruero))

def proceso_caja(env, nombre, trabajador, gruero):
    # Procesamiento de la caja
    with trabajador.request() as req:
        yield req
        yield env.timeout(t_proceso_caja())
        categoria = random.choices(CATEGORIAS, PROB)[0]
        yield env.timeout(t_armado_caja())

        cajas_en_pallet[categoria] += 1
        print(f"[{env.now:.1f}] {nombre} agregada al pallet de {categoria} (total en construcción: {cajas_en_pallet[categoria]})")

        # Verificar si se completa el pallet
        if cajas_en_pallet[categoria] >= CAJAS_POR_PALLET:
            cajas_en_pallet[categoria] -= CAJAS_POR_PALLET
            pallets[categoria] += 1
            print(f"[{env.now:.1f}] Pallet completo de {categoria}, enviado a almacenamiento por gruero")

            # Gruero maneja el pallet
            with gruero.request() as reqg:
                yield reqg
                yield env.timeout(T_POSICIONAR_PALLET)
                yield env.timeout(T_GRUERO)
                print(f"[{env.now:.1f}] Gruero almacena pallet de {categoria} en área de residuos")

def llegada_pallets(env, trabajador, gruero, dia):
    for i in range(PALLETS_POR_DIA):
        # Intervalos aleatorios cortos para separar pallets
        yield env.timeout(random.expovariate(1))
        print(f"\n[{env.now:.1f}] Día {dia} - Pallet{i+1} llega al área de subestandar")
        env.process(proceso_pallet(env, f"D{dia}-Pallet{i+1}", trabajador, gruero))

# ------------------------------
# Simulación
# ------------------------------
env = simpy.Environment()
trabajador = simpy.Resource(env, capacity=1)
gruero = simpy.Resource(env, capacity=1)

for d in range(1, DIAS + 1):
    env.process(llegada_pallets(env, trabajador, gruero, d))
    env.run(until=d * TURNO)

    print(f"\n--- Fin del día {d} ---")
    total_pallets = sum(pallets.values())
    print(f"Pallets completos acumulados: {total_pallets}")
    for cat in CATEGORIAS:
        print(f"  {cat}: {pallets[cat]} pallets completos, {cajas_en_pallet[cat]} cajas sobrantes")
