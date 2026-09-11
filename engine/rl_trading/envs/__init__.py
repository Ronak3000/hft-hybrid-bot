from .queue_replay_env import QueueReplayEnv

__all__ = ["QueueReplayEnv", "TradingEnv"]


def __getattr__(name: str):
    if name == "TradingEnv":
        from .trading_env import TradingEnv

        return TradingEnv
    raise AttributeError(name)
