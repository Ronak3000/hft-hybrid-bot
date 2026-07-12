from fastapi import APIRouter
from pydantic import BaseModel
from api.core.celery_app import celery_app

router = APIRouter(prefix="/api/training", tags=["RL Training"])

class TrainingRequest(BaseModel):
    symbol: str
    start_date: str
    end_date: str
    epochs: int = 500
    learning_rate: float = 0.0003
    entropy_coef: float = 0.01
    
    # Advanced Market Dynamics
    starting_cash: float = 1000000.0
    base_trade_size: float = 0.5
    max_inventory: float = 6.0
    maker_fee: float = -0.0001
    penalty_factor: float = 0.1
    kappa: float = 1.5

@router.post("/start")
async def start_training_job(req: TrainingRequest):
    """
    Dispatches a heavy PPO training job to the Celery worker cluster via Redis.
    """
    task = celery_app.send_task(
        "worker.tasks.rl_training.train_ppo_model",
        args=[
            req.symbol, req.start_date, req.end_date, 
            req.epochs, req.learning_rate, req.entropy_coef,
            req.starting_cash, req.base_trade_size, req.max_inventory,
            req.maker_fee, req.penalty_factor, req.kappa
        ]
    )
    
    return {
        "message": "Training job dispatched to the cluster.",
        "job_id": task.id,
        "status_url": f"/api/training/status/{task.id}"
    }

@router.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """
    Allows the Next.js UI to poll the progress of the training job.
    """
    task_result = celery_app.AsyncResult(job_id)
    
    if task_result.state == 'PENDING':
        return {"state": task_result.state, "status": "Waiting for an available compute node..."}
    elif task_result.state == 'PROGRESS':
        return {"state": task_result.state, "progress": task_result.info}
    elif task_result.state == 'SUCCESS':
        return {"state": task_result.state, "result": task_result.result}
    else:
        return {"state": task_result.state, "error": str(task_result.info)}