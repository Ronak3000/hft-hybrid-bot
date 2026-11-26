"""Long/flat spot paper policy. A decision on bar t fills at t+1 close proxy."""
import hashlib
import json
import time
import gymnasium as gym
import numpy as np
from gymnasium import spaces
from engine.market_data.candles import MINUTE, URL, get_bars, history
from engine.research.trader_trace import TraderTrace

ENV = "ApexBinanceUSMinute-v1"


def split_sessions(rows):
    sessions = []
    for bar in rows:
        if not sessions or bar[0] != sessions[-1][-1][0]+MINUTE:
            sessions.append([])
        sessions[-1].append(bar)
    return sessions


def next_live_bars(symbol, first, stop, check):
    """Tolerate a newly closed bar arriving late, never bridge an actual gap."""
    rows = get_bars(symbol, first, stop, check, allow_gaps=True)
    expected = first
    for row in rows:
        if row[0] != expected:
            raise ValueError("Binance.US live candle gap; stopped without simulating a fill.")
        expected += MINUTE
    if stop - expected >= 2 * MINUTE:
        raise ValueError("Binance.US live candles are stale; stopped without simulating a fill.")
    return rows


class CandleEnv(gym.Env):
    def __init__(self, rows, sessions=None, symbol="BTCUSDT"):
        self.rows = rows
        self.symbol = symbol
        self.sessions = sessions or [rows]
        self.episode = 0
        self.action_space = spaces.Discrete(2)
        self.observation_space = spaces.Box(-10,10,(5,),dtype=np.float32)

    def observe(self, bar):
        _,o,h,l,c,v = bar
        return np.clip([np.log(c/o)*100, np.log(h/o)*100, np.log(l/o)*100,
                        np.log1p(v), self.position],-10,10).astype(np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.rows = self.sessions[self.episode % len(self.sessions)]
        self.episode += 1
        self.i = self.position = self.fills = 0
        self.pnl = 0.
        return self.observe(self.rows[0]), {}

    def advance(self, old, new, action):
        if new[0]-old[0] != MINUTE:
            raise ValueError("Cannot apply an action across a candle gap.")
        # No same-bar hindsight: inventory held before the decision earns the move.
        change = self.position * (new[4]-old[4]) * .001
        self.pnl += change
        self.fills += int(self.position != int(action))
        self.position = int(action)
        return self.observe(new), change

    def step(self, action):
        self.i += 1
        obs, reward = self.advance(self.rows[self.i-1], self.rows[self.i], action)
        return obs, reward, self.i == len(self.rows)-1, False, {}

    def result(self):
        asset = self.symbol.removesuffix("USDT")
        return dict(net_pnl=self.pnl, fills=self.fills,inventory_units=self.position*.001,
                    **({"inventory_btc":self.position*.001} if asset=="BTC" else {}),
                    assumption=f"0 or 0.001 {asset}, next closed candle close-price proxy, zero fees/slippage; paper only")


def run(kind, req, root, job, update, check, weights=None, *, paused=lambda:False, recorded=None):
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import BaseCallback
    import torch
    if kind == "live":
        model = PPO.load(weights,device="cpu")
        stop = int(time.time()*1000)//MINUTE*MINUTE
        recent = get_bars(req.symbol, stop - 30 * MINUTE, stop, check, allow_gaps=True)
        if not recent or recent[-1][0] < stop - 2 * MINUTE:
            raise ValueError("Binance.US has not supplied a recent closed candle.")
        warm = split_sessions(recent)[-1]
        last = warm[-1]
        trace = TraderTrace(source=f"Binance.US {req.symbol} 1m OHLCV")
        for bar in warm[:-1]:
            trace.add(bar[0]//1000,*bar[1:5],0,0,0)
            trace.points[-1]["pnl"] = None  # market history, before the paper session
        trace.add(last[0]//1000,*last[1:5],0,0,0)
        env = CandleEnv([last],symbol=req.symbol)
        buys = sells = 0
        obs,_ = env.reset()
        deadline = time.monotonic()+req.seconds
        update("Connected · waiting for next minute close",{**env.result(),"closed_bar_steps":0,**trace.payload()})
        while time.monotonic()<deadline:
            check()
            stop = int(time.time()*1000)//MINUTE*MINUTE
            if stop > last[0]+MINUTE:
                for bar in next_live_bars(req.symbol,last[0]+MINUTE,stop,check):
                    action,_ = model.predict(obs,deterministic=True)
                    before = env.position
                    obs,_ = env.advance(last,bar,env.position if paused() else action)
                    buys += int(env.position > before)
                    sells += int(env.position < before)
                    last = bar
                    env.i += 1
                    trace.add(bar[0]//1000,*bar[1:5],env.pnl,env.position*.001,env.fills)
                    trace.points[-1].update(buys=buys,sells=sells)
                    update("Live closed candle received",{**env.result(),"closed_bar_steps":env.i,**trace.payload()})
            time.sleep(.5)
        return {**env.result(),"closed_bar_steps":env.i,**trace.payload()}
    rows,digest = recorded if recorded is not None else history(root,req,check,update)
    all_sessions = split_sessions(rows)
    sessions = [s for s in all_sessions if len(s)>=2]
    if not sessions:
        raise ValueError("No consecutive pair of real one-minute candles.")
    first = rows[0][0] if recorded else int(req.start.timestamp())*1000
    stop = rows[-1][0]+MINUTE if recorded else int(req.end.timestamp())*1000
    gaps = []
    cursor = first
    for group in all_sessions:
        if group[0][0]>cursor:
            gaps.append([cursor,group[0][0]])
        cursor = group[-1][0]+MINUTE
    if cursor<stop: gaps.append([cursor,stop])
    coverage = dict(missing_minutes=sum((b-a)//MINUTE for a,b in gaps), gaps_utc_ms=gaps,
                    continuous_episodes=len(sessions),isolated_bars=len(all_sessions)-len(sessions))
    env = CandleEnv(rows,sessions,req.symbol)
    if kind == "backtest":
        model = PPO.load(weights,device="cpu")
        trace = TraderTrace(60*max(1,(len(rows)+999)//1000))
        from engine.research.replay_stats import ReplayStats
        stats = ReplayStats()
        pnl = 0.
        fills = 0
        points = []
        for idx, group in enumerate(sessions):
            obs,_ = env.reset()
            stats.lots.clear()
            segment = TraderTrace(trace.seconds,source=f"Binance.US {req.symbol} 1m OHLCV")
            origin = group[0][0]//1000
            segment.add(0,*group[0][1:5],pnl,0,fills)
            segment.points[-1].update(stats.mark(pnl))
            while env.i < len(group)-1:
                check()
                action,_ = model.predict(obs,deterministic=True)
                old_position = env.position
                obs,*_ = env.step(action)
                bar = group[env.i]
                if old_position != env.position:
                    stats.fill("buy" if env.position else "sell",bar[4],".001")
                segment.add(bar[0]//1000-origin,*bar[1:5],pnl+env.pnl,env.position*.001,fills+env.fills)
                segment.points[-1].update(stats.mark(pnl+env.pnl))
            for point in segment.points: point["time"] += origin
            segment.points[0]["gap_before"] = idx>0 or origin*1000>first
            points.extend(segment.points)
            pnl += env.pnl
            fills += env.fills
        return {**env.result(),"net_pnl":pnl,"fills":fills,"bars":len(rows),"data_sha256":digest,
                **segment.payload(),"chart":points,**coverage}
    p = req.ppo
    torch.set_num_threads(p.torch_threads)
    class Progress(BaseCallback):
        def _on_step(self):
            check()
            if self.num_timesteps % p.n_steps == 0:
                update(f"Training candle PPO: {self.num_timesteps:,}/{req.steps:,} steps")
            return True
    update(f"Training on {len(rows):,} real candles in {len(sessions)} episodes; {coverage['missing_minutes']} missing minutes excluded")
    model = PPO("MlpPolicy",env,n_steps=p.n_steps,batch_size=p.batch_size,n_epochs=p.n_epochs,
                learning_rate=p.learning_rate,gamma=p.gamma,gae_lambda=p.gae_lambda,clip_range=p.clip_range,
                clip_range_vf=p.clip_range_vf,ent_coef=p.entropy_coefficient,vf_coef=p.value_coefficient,
                max_grad_norm=p.max_grad_norm,target_kl=p.target_kl,normalize_advantage=p.normalize_advantage,
                seed=p.seed,device=p.device,policy_kwargs=dict(net_arch=[p.hidden_width]*p.hidden_layers,
                ortho_init=p.orthogonal_init,activation_fn=torch.nn.ReLU if p.activation=="relu" else torch.nn.Tanh))
    model.learn(req.steps,callback=Progress())
    path = root/"models"/(job+".zip")
    path.parent.mkdir(exist_ok=True,parents=True)
    model.save(path)
    meta = dict(environment=ENV,held_out_splits_used=[],total_timesteps=req.steps,
                model_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),data_sha256=digest,
                configuration=p.model_dump(),coverage=coverage,execution=env.result()["assumption"],
                archive_window=dict(symbol=req.symbol,start=req.start.isoformat(),end=req.end.isoformat(),source=URL))
    path.with_suffix(".json").write_text(json.dumps(meta),encoding="utf-8")
    return dict(model_id=job,symbol=req.symbol,training_steps=req.steps,bars=len(rows),data_sha256=digest,source=URL,**coverage)
