from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import live, backtest, training # Import the new router

app = FastAPI(title="Quant Core API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(live.router)
app.include_router(backtest.router)
app.include_router(training.router) # Mount the training endpoints