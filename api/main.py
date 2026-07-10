from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import all platform routers
from routes import training, models, live, backtest

app = FastAPI(title="Quant IaaS Platform")

# CORS configuration for the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the Routers
app.include_router(training.router)  # PPO dispatch and status polling
app.include_router(models.router)    # Supabase PostgreSQL registry
app.include_router(live.router)      # WebSockets for real-time LOB and execution
app.include_router(backtest.router)  # Historical simulation endpoints

@app.get("/")
def read_root():
    return {"status": "operational", "service": "HFT API Gateway"}