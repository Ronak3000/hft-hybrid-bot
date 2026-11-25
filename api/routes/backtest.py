from fastapi import APIRouter, Depends
from api.workbench import Test, RecordedTest, replay_files, launch, operator, state

router = APIRouter(prefix="/api/backtest", tags=["Historical paper test"])

@router.post("/start", status_code=202, dependencies=[Depends(operator)])
def start_test(req: Test | RecordedTest):
    return launch("backtest", req)

@router.get("/status/{job_id}")
def status(job_id: str):
    return state(job_id)


@router.get("/recordings")
def recordings_list(symbol:str="BTCUSDT"):
    if symbol not in ("BTCUSDT","ETHUSDT","SOLUSDT"): return []
    return [{"id":key,"family":v[0],"label":v[1].stem} for key,v in replay_files(symbol).items()]
