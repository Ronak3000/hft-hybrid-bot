"""Single-worker research jobs. No exchange credentials, order endpoints or fake feed."""
import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from threading import Lock, Thread, Event
import time
import re
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from typing import Literal

from engine.market_data.history import archive_dataset, load_dataset, window
from engine.market_data import verify_capture
from api.policy_settings import PPOSettings, SimulationSettings, Settings, command_options

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv("APEX_WORKSPACE_DATA", ROOT / "data/workbench"))
LOCK = Lock()
ACTIVE = None
CANCEL = Event()
PAUSE = Event()
ACTIVE_KIND = None


class JobCanceled(RuntimeError):
    pass


class HistoricalWindow(Settings):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    start: datetime
    end: datetime
    max_dataset_gb: float = Field(100, ge=0.1, le=10000, description="Disk budget for the complete dataset")

    @model_validator(mode="after")
    def validate_window(self):
        self.start, self.end = window(self.start, self.end)
        return self


class LearningControls(Settings):
    steps: int = Field(default=2048, ge=2, le=100000000)
    ppo: PPOSettings = Field(default_factory=PPOSettings)
    simulation: SimulationSettings = Field(default_factory=SimulationSettings)

    @model_validator(mode="after")
    def steps_match(self):
        if self.steps % self.ppo.n_steps:
            raise ValueError("Total training steps must be divisible by PPO rollout steps.")
        return self


class Train(HistoricalWindow, LearningControls):
    pass


class CandleTrain(HistoricalWindow):
    symbol: Literal["BTCUSDT","ETHUSDT","SOLUSDT"] = "BTCUSDT"
    source: Literal["candles"]
    steps: int = Field(default=2048, ge=2, le=100000000)
    ppo: PPOSettings = Field(default_factory=PPOSettings)

    @model_validator(mode="after")
    def budget(self):
        minutes = (self.end-self.start).total_seconds() / 60
        if not 2 <= minutes <= 366*1440 or self.steps < minutes-1 or self.steps % self.ppo.n_steps:
            raise ValueError("Choose 2 minutes to 366 days and enough rollout-multiple steps to cover every candle.")
        return self


class KeylessTrain(LearningControls):
    symbol: Literal["BTCUSDT"] = "BTCUSDT"
    recording: str = Field(pattern=r"^[a-zA-Z0-9_.-]{1,160}$")


def recordings():
    """Only planned training recordings, never validation/test or arbitrary paths."""
    from engine.research import load_study_plan
    result = {}
    for plan_path in sorted((ROOT / "data/studies").glob("*.json")):
        if plan_path.name.endswith((".manifest.json", "-experiment.json")):
            continue
        plan = load_study_plan(plan_path)
        if plan["capture_configuration"]["symbol"] != "BTCUSDT":
            continue
        for item in plan["sessions"]:
            path = (ROOT / plan["capture_directory"] / item["capture_file"]).resolve()
            if item["split"] == "train" and path.is_relative_to((ROOT / "data/captures").resolve()) and path.is_file():
                result[path.name] = path
    return result


class Test(HistoricalWindow):
    symbol: Literal["BTCUSDT","ETHUSDT","SOLUSDT"] = "BTCUSDT"
    model_id: str = Field(pattern="^[a-zA-Z0-9_-]{1,100}$")


class RecordedTest(Settings):
    symbol: Literal["BTCUSDT","ETHUSDT","SOLUSDT"] = "BTCUSDT"
    model_id: str = Field(pattern="^[a-zA-Z0-9_-]{1,100}$")
    recording_id: str = Field(min_length=1,max_length=180)


def replay_files(symbol="BTCUSDT"):
    files = {"study:"+k: ("l2",v) for k,v in recordings().items()}
    for path in (DATA/"archive"/"captures").glob("*/*.jsonl"):
        files["archive:"+path.name] = ("l2",path)
    if symbol!="BTCUSDT":
        files.clear()
    for path in (DATA/"candles"/symbol).glob("*.json"):
        files["candles:"+path.stem] = ("candles",path)
    return files


class Live(BaseModel):
    symbol: Literal["BTCUSDT","ETHUSDT","SOLUSDT"] = "BTCUSDT"
    model_id: str = Field(pattern="^[a-zA-Z0-9_-]{1,100}$")
    seconds: int = Field(default=120, ge=10, le=300)


def operator(request: Request):
    key = os.getenv("APEX_OPERATOR_TOKEN")
    if key:
        if not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + key):
            raise HTTPException(401, "Enter the server's operator token.")
    else:
        local = {"localhost", "127.0.0.1", "::1"}
        origin = request.headers.get("origin")
        if (os.getenv("RENDER") or not request.client or request.client.host not in local
                or request.url.hostname not in local or (origin and urlparse(origin).hostname not in local)):
            raise HTTPException(403, "Configure APEX_OPERATOR_TOKEN to enable hosted jobs.")


def models():
    # Only operator-owned server directories. Never accept an uploaded pickle or path.
    for directory in (DATA / "models", ROOT / "engine/saved_models"):
        for sidecar in sorted(directory.glob("*.json")):
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                if (meta.get("environment") not in ("ApexHFTQueueReplay-v0", "ApexBinanceUSMinute-v1")
                        or meta.get("held_out_splits_used") != []
                        or not isinstance(meta.get("total_timesteps"), int)
                        or meta["total_timesteps"] < 1):
                    continue
                weights = sidecar.with_suffix(".zip")
                if hashlib.sha256(weights.read_bytes()).hexdigest() != meta["model_sha256"]:
                    continue
                if "archive_window" in meta:
                    symbol = meta["archive_window"]["symbol"]
                else:
                    plan_name = meta["study_plan_file"]
                    if Path(plan_name).name != plan_name:
                        continue
                    plan = (ROOT / "data/studies" / plan_name).read_bytes()
                    if hashlib.sha256(plan).hexdigest() != meta["study_plan_sha256"]:
                        continue
                    symbol = json.loads(plan)["capture_configuration"]["symbol"]
                yield sidecar.stem, symbol, weights, meta
            except (OSError, AttributeError, KeyError, TypeError, ValueError):
                continue


def trained_until(meta):
    if "archive_window" in meta:
        return datetime.fromisoformat(meta["archive_window"]["end"].replace("Z", "+00:00")).timestamp()
    # Existing sealed-study models must also pass a chronological holdout check.
    plan = json.loads((ROOT / "data/studies" / meta["study_plan_file"]).read_text())
    last = 0
    for source in meta["training_captures"]:
        path = ROOT / plan["capture_directory"] / source["capture_file"]
        if verify_capture(path)["sha256"] != source["sha256"]:
            raise ValueError("Training provenance mismatch.")
        with path.open("rb") as f:
            for line in f:
                last = max(last, json.loads(line)["received_time_ns"])
    return last / 1e9


def execute(kind, req, job, update, check=lambda: None):
    if kind != "train":
        row = next((x for x in models() if x[0] == req.model_id and x[1] == req.symbol), None)
        if row is None:
            raise ValueError("No verified saved model matches this symbol and model ID.")
        _, _, weights, meta = row
        if isinstance(req,Test) and req.start.timestamp() < trained_until(meta):
            raise ValueError("Test window must start at or after the end of all training data.")
    selected = None
    cached = None
    if isinstance(req,RecordedTest):
        entry = replay_files(req.symbol).get(req.recording_id)
        if entry is None:
            raise ValueError("Recording no longer available.")
        family,selected = entry
        if (family == "candles") != (meta["environment"] == "ApexBinanceUSMinute-v1"):
            raise ValueError("Recording is incompatible with this checkpoint.")
        if family == "candles":
            raw = selected.read_bytes()
            if hashlib.sha256(raw).hexdigest() != selected.stem:
                raise ValueError("Candle recording hash mismatch.")
            rows = json.loads(raw)
            cached = rows,selected.stem
            first = rows[0][0]/1000
        else:
            verify_capture(selected)
            with selected.open(encoding="utf8") as f:
                first = min(r["received_time_ns"] for r in map(json.loads,f) if r["kind"]!="metadata")/1e9
        if first < trained_until(meta):
            raise ValueError("Choose a recording later than the model's training data.")
    if isinstance(req,CandleTrain) or (kind != "train" and meta["environment"] == "ApexBinanceUSMinute-v1"):
        from engine.rl_trading.candle_policy import run
        return run(kind,req,DATA,job,update,check,None if kind=="train" else weights,paused=PAUSE.is_set,recorded=cached)
    recording = None
    if isinstance(req, KeylessTrain):
        choices = recordings()
        if req.recording == "auto":
            recording = next(reversed(choices.values()), None)
        elif req.recording != "download":
            recording = choices.get(req.recording)
            if recording is None:
                raise ValueError("Selected recording no longer exists. Select another recording or download the free sample.")
    if selected:
        paths = (selected,)
    elif recording:
        update("Verifying Binance recording: " + recording.name)
        paths = (recording,)
        source_args = ["--recorded-window", str(recording)]
        evidence = {"recording": recording.name, "capture_sha256": verify_capture(recording)["sha256"]}
    elif kind != "live":
        if isinstance(req, KeylessTrain):
            start = datetime(2024, 1, 1, tzinfo=timezone.utc)
            end = start + timedelta(minutes=1)
            budget = 1
            update("Acquiring free Binance BTCUSDT sample: 2024-01-01 00:00–00:01 UTC")
        else:
            start, end, budget = req.start, req.end, req.max_dataset_gb
        dataset = archive_dataset(DATA / "archive", req.symbol, start, end, update,
                                  max_download_bytes=int(budget * 1024**3), check=check)
        dataset_meta, paths = load_dataset(dataset)
        source_args = ["--archive-dataset", str(dataset)]
        evidence = {"dataset_manifest": dataset.name, "data_bytes": dataset_meta["byte_count"]}
    if kind == "train":
        update("Training PPO on verified depth and trades")
        output = DATA / "models" / (job + ".zip")
        cmd = [sys.executable, "-u", str(ROOT / "scripts/train_queue_ppo.py"), *source_args,
               "--output", str(output), "--total-timesteps", str(req.steps),
               "--tick-size", "0.01",
               "--action-schema-version", "3", "--observation-schema-version", "2",
               "--max-half-spread-ticks", str(max(req.simulation.half_spread_tick_choices)),
               *command_options(req.ppo, req.simulation)]
        log_path = DATA / "jobs" / (job + ".log")
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=log)
            next_progress = 0.0
            try:
                while proc.poll() is None:
                    check()
                    if time.monotonic() >= next_progress:
                        next_progress = time.monotonic() + 2
                        with log_path.open("rb") as tail:
                            tail.seek(max(log_path.stat().st_size - 4096, 0))
                            completed = re.findall(r"total_timesteps\s*\|\s*(\d+)", tail.read().decode(errors="replace"))
                        if completed:
                            update(f"Training PPO: {int(completed[-1]):,} / {req.steps:,} steps")
                    time.sleep(0.25)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
        if proc.returncode:
            with log_path.open("rb") as log:
                log.seek(max(log_path.stat().st_size - 2000, 0))
                raise RuntimeError(log.read().decode(errors="replace"))
        return {"model_id": job, "training_steps": req.steps, "capture_count": len(paths),
                **evidence}
    from stable_baselines3 import PPO
    import torch
    torch.set_num_threads(1)
    predictor = PPO.load(weights, device="cpu")
    if kind == "live":
        from api.paper_live import run_live
        update("Connecting to Binance public depth and trades")
        return run_live(req.symbol, predictor, meta["configuration"], req.seconds, DATA / "live" / (job + ".jsonl"), update, check=check,paused=PAUSE.is_set)
    from engine.research.ppo_evaluation import _evaluate_capture
    update("Testing frozen weights on a later historical window")
    from decimal import Decimal
    results = []
    from engine.research.trader_trace import TraderTrace
    width = 5 if selected else max(1,int((req.end-req.start).total_seconds()/900))
    trace = TraderTrace(width,"Binance Spot sampled book midpoint")
    offset = Decimal(0)
    count = 0
    from engine.research.replay_stats import ReplayStats
    stats = ReplayStats()
    previous_sim = None
    seen = 0
    episode_pnl = Decimal(0)
    def observe(env,info):
        nonlocal previous_sim,seen,offset,count,episode_pnl
        if env.simulator is not previous_sim:
            offset += episode_pnl
            count += seen
            seen = 0
            stats.lots.clear()  # independent accounts: never match across resets
            previous_sim = env.simulator
        for fill in env.simulator.fills[seen:]:
            stats.fill(fill.side.value,fill.price,fill.quantity,fill.fee)
        seen = len(env.simulator.fills)
        episode_pnl = Decimal(info["net_worth"])-env.config.initial_cash
        mid = env._mid_or_previous()
        trace.add(info["decision_time_ns"]//10**9,mid,mid,mid,mid,
                  offset+Decimal(info["net_worth"])-env.config.initial_cash,info["inventory"],count+info["total_fills"])
        trace.points[-1].update(stats.mark(offset+episode_pnl))
    for i, path in enumerate(paths):
        check()
        update(f"Testing frozen weights: chunk {i + 1}/{len(paths)}")
        results.append(_evaluate_capture(predictor, path, meta["configuration"], check=check,on_step=observe))
    return {"sessions": results, "fills": sum(x["fills"] for x in results),
            "net_pnl": str(sum((Decimal(x["net_pnl"]) for x in results), Decimal(0))),
            "source": selected.name if selected else dataset.name, **trace.payload(), "episode_accounting": "sum of independent chunk P&Ls; not one continuous portfolio"}


def state(job):
    if len(job) != 32 or any(c not in "0123456789abcdef" for c in job):
        raise HTTPException(404, "Unknown job")
    path = DATA / "jobs" / (job + ".json")
    if not path.exists():
        raise HTTPException(404, "Unknown job")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value["status"] == "running" and ACTIVE != job:
        return {**value, "status": "failed", "message": "Job interrupted by server restart."}
    return {**value,"paused":ACTIVE==job and PAUSE.is_set()}


def launch(kind, req):
    global ACTIVE, ACTIVE_KIND
    if isinstance(req, Train):
        minimum = (req.end - req.start).total_seconds() / (req.simulation.decision_interval_ns / 1e9)
        if req.steps < minimum:
            raise HTTPException(422, "Training steps cannot cover this range. Use Estimate to choose a sufficient rollout-multiple budget.")
    job = uuid4().hex
    path = DATA / "jobs" / (job + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    last_result = None
    def save(status, message, result=None):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(job_id=job, kind=kind, request=req.model_dump(mode="json"),
                                       status=status, message=message, result=result)), encoding="utf-8")
        for attempt in range(8):
            try:
                tmp.replace(path)
                break
            except PermissionError:
                if attempt==7: raise
                time.sleep(.02*(attempt+1))
    def update(message, result=None):
        nonlocal last_result
        if result is not None:
            last_result = result
        save("running", message, result)
    def work():
        global ACTIVE
        try:
            result = execute(kind, req, job, update, check=CANCEL_CHECK)
            outcome = ("completed", "Completed", result)
        except JobCanceled as exc:
            outcome = ("canceled", str(exc), last_result)
        except Exception as exc:
            outcome = ("failed", str(exc) or type(exc).__name__, last_result)
        with LOCK:
            try:
                save(*outcome)
            finally:
                ACTIVE = None
    with LOCK:
        if ACTIVE is not None:
            raise HTTPException(409, "A research job is already running.")
        update("Starting")
        CANCEL.clear()
        PAUSE.clear()
        ACTIVE_KIND = kind
        ACTIVE = job
        Thread(target=work, daemon=True).start()
    return {"job_id": job}


def set_paused(job, paused):
    with LOCK:
        if ACTIVE != job or ACTIVE_KIND != "live":
            raise HTTPException(409,"No matching running live session.")
        (PAUSE.set if paused else PAUSE.clear)()
    return {"paused":paused}


def CANCEL_CHECK():
    if CANCEL.is_set():
        raise JobCanceled("Canceled by operator; verified downloaded chunks are retained.")


def cancel(job):
    with LOCK:
        if ACTIVE != job:
            raise HTTPException(409, "This job is not running.")
        CANCEL.set()
    return {"job_id": job, "status": "cancellation_requested"}
