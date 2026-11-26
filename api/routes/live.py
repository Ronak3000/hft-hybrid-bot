from fastapi import APIRouter, Depends
from api.workbench import Live, launch, operator, state
from api.workbench import set_paused

router = APIRouter(prefix="/api/live", tags=["Live paper inference"])

@router.post("/start", status_code=202, dependencies=[Depends(operator)])
def start_live(req: Live):
    return launch("live", req)

@router.get("/status/{job_id}")
def status(job_id: str):
    return state(job_id)


@router.post("/pause/{job_id}", dependencies=[Depends(operator)])
def pause(job_id:str, paused:bool):
    return set_paused(job_id,paused)
