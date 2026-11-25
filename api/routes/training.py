from fastapi import APIRouter, Depends
from api.workbench import Train, CandleTrain, KeylessTrain, recordings, launch, operator, state, cancel
from api.policy_settings import PPOSettings, SimulationSettings
from engine.market_data.history import archive_estimate

router = APIRouter(prefix="/api/training", tags=["PPO research"])

@router.post("/start", status_code=202, dependencies=[Depends(operator)])
def start_training(req: CandleTrain | Train | KeylessTrain):
    return launch("train", req)

@router.get("/status/{job_id}")
def status(job_id: str):
    return state(job_id)


@router.get("/settings")
def settings():
    return {"recordings": list(reversed(recordings())), "ppo": PPOSettings.model_json_schema(), "simulation": SimulationSettings.model_json_schema(),
            "defaults": {"ppo": PPOSettings().model_dump(), "simulation": SimulationSettings().model_dump()}}


@router.post("/estimate")
def estimate(req: Train):
    from math import ceil
    estimate = archive_estimate(req.start, req.end)
    minimum = ceil((req.end - req.start).total_seconds() / (req.simulation.decision_interval_ns / 1e9))
    estimate["minimum_training_steps"] = ceil(minimum / req.ppo.n_steps) * req.ppo.n_steps
    estimate["training_budget_covers_range"] = req.steps >= minimum
    return estimate


@router.post("/cancel/{job_id}", dependencies=[Depends(operator)])
def stop(job_id: str):
    return cancel(job_id)
