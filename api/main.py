import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import all platform routers
from api.routes import training, models, live, backtest

app = FastAPI(title="Quant IaaS Platform")

# CORS: read allowed origins from env var (comma-separated).
# Set CORS_ORIGINS=https://your-app.vercel.app on Render.
# Falls back to localhost for local development.
_cors_env = os.getenv("CORS_ORIGINS", "http://localhost:3000")
allowed_origins = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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