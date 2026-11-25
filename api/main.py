import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import all platform routers
from api.routes import training, models, live, backtest

app = FastAPI(title="ApexHFT Research Workbench")

# CORS: read allowed origins from env var (comma-separated).
# Set CORS_ORIGINS=https://your-app.vercel.app on Render.
# Falls back to localhost for local development.
_cors_env = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:4317,http://127.0.0.1:4317")
allowed_origins = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the Routers
app.include_router(training.router)
app.include_router(models.router)
app.include_router(live.router)
app.include_router(backtest.router)

@app.get("/")
def read_root():
    return {"status": "operational", "service": "HFT API Gateway",
            "market_data_policy": "real_exchange_inputs_only",
            "workflows": ["candle_train", "historical_test", "live_paper"],
            "exchange_order_routing": False}


@app.get("/health")
def health():
    return read_root()
