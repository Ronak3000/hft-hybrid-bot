from fastapi import APIRouter
from api.workbench import models

router = APIRouter(prefix="/api/models", tags=["Verified PPO weights"])

@router.get("/{symbol}")
def list_models(symbol: str):
    # Verified sidecars are the registry; listing is read-only and needs no database.
    rows = {}
    for name, sym, _, meta in models():
        if sym == symbol.upper():
            rows.setdefault(name, {
                "id": name, "symbol": sym, "sha256": meta["model_sha256"],
                "environment": meta["environment"], "steps": meta["total_timesteps"],
                "training": meta.get("archive_window", meta.get("study_name")),
            })
    return {"models": [rows[name] for name in sorted(rows)]}
