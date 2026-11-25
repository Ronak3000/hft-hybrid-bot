"""Feed real-time public exchange records to the same forward-only PPO environment."""
import asyncio
from queue import Queue, Empty, Full
from threading import Event, Thread
import time

from engine.market_data.l2 import CaptureWriter
from engine.research.ppo_evaluation import policy_environment
from scripts.capture_binance_l2 import _ConnectionStats, _connect_and_capture


def run_live(symbol, model, config, duration, journal, update, *, check=lambda: None, paused=lambda:False):
    from engine.research.trader_trace import TraderTrace
    from decimal import Decimal
    import numpy as np
    trace = TraderTrace(1,"Binance Spot sampled book midpoint")
    records = Queue(maxsize=4096)
    stop, done = Event(), Event()
    errors = []
    meta = {"venue": "binance_spot", "symbol": symbol, "source": "Binance Spot live depth and public trades"}

    def produce():
        try:
            with CaptureWriter(journal, meta) as capture:
                class Sink:
                    def write(self, kind, payload, received):
                        if stop.is_set():
                            raise RuntimeError("Paper session stopped.")
                        if kind in {"gap", "trade_gap", "disconnect"}:
                            capture.write(kind, payload, received)
                            raise ValueError(f"Live continuity lost: {kind}")
                        capture.write(kind, payload, received)
                        try:
                            records.put_nowait(dict(kind=kind, payload=payload, received_time_ns=received))
                        except Full:
                            raise RuntimeError("Live consumer fell behind; stopping paper execution.")

                async def connect():
                    task = asyncio.create_task(_connect_and_capture(symbol, 1000, Sink(), 10**9, _ConnectionStats()))
                    try:
                        deadline = time.monotonic() + duration
                        while not task.done() and not stop.is_set() and time.monotonic() < deadline:
                            check()
                            await asyncio.sleep(0.1)
                        if task.done():
                            raise RuntimeError("Public stream ended: " + str(await task))
                    finally:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                asyncio.run(connect())
        except Exception as exc:
            errors.append(str(exc))
        finally:
            done.set()

    def stream():
        yield {"kind": "metadata", "payload": meta, "received_time_ns": 0}
        while True:
            check()
            if errors:
                raise RuntimeError(errors[0])
            try:
                event = records.get(timeout=0.2)
            except Empty:
                if done.is_set():
                    return
                continue
            if time.time_ns() - event["received_time_ns"] > 5_000_000_000:
                raise RuntimeError("Stale live record; paper execution halted.")
            yield event

    env = policy_environment((), config, stream_records=enumerate(stream(), 1))
    thread = Thread(target=produce, daemon=True)
    thread.start()
    try:
        obs, info = env.reset()
        while True:
            action, _ = model.predict(obs, deterministic=True)
            if paused():
                env.simulator.invalidate_open_orders(env.current_decision_time_ns)
                action = np.zeros_like(action)
            obs, _, _, ended, info = env.step(action)
            mid = env._mid_or_previous()
            pnl = Decimal(info["net_worth"]) - env.config.initial_cash
            trace.add(info["decision_time_ns"]//10**9,mid,mid,mid,mid,pnl,info["inventory"],info["total_fills"])
            info.update(net_pnl=str(pnl), **trace.payload())
            update("Live paper inference", info)
            if ended:
                if info["reason"] != "end_of_capture" or not info["episode_steps"]:
                    raise RuntimeError("Live episode stopped: " + info["reason"])
                return {**info, "journal": journal.name, "paper_only": True}
    finally:
        stop.set()
        thread.join(20)
        env.close()
