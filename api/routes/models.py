from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from api.core.database import supabase

router = APIRouter(prefix="/api/models", tags=["Model Registry"])

class ModelRegistryRequest(BaseModel):
    symbol: str
    start_date: str
    end_date: str
    model_filename: str
    hyperparameters: Dict[str, Any]

@router.post("/register")
async def register_model(req: ModelRegistryRequest):
    try:
        # STRIP THE SLASHES before saving to DB
        clean_symbol = req.symbol.replace("/", "").replace("-", "").upper()
        
        data = {
            "symbol": clean_symbol,
            "start_date": req.start_date,
            "end_date": req.end_date,
            "model_filename": req.model_filename,
            "hyperparameters": req.hyperparameters
        }
        
        response = supabase.table("trained_models").insert(data).execute()
        return {"status": "success", "data": response.data}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/{symbol:path}")
async def get_models_by_symbol(symbol: str):
    try:
        # STRIP THE SLASHES before querying the DB
        clean_symbol = symbol.replace("/", "").replace("-", "").upper()
        
        response = supabase.table("trained_models").select("*").eq("symbol", clean_symbol).execute()
        return {"status": "success", "models": response.data}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")