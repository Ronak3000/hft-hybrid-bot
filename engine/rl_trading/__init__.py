from gymnasium.envs.registration import register

# Register the environment so it can be created via gym.make() if needed in the future
register(
    id="InstitutionalHFT-v0",
    entry_point="engine.rl_trading.envs.trading_env:TradingEnv",
)

register(
    id="ApexHFTQueueReplay-v0",
    entry_point="engine.rl_trading.envs.queue_replay_env:QueueReplayEnv",
)
