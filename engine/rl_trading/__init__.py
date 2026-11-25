from gymnasium.envs.registration import register

register(
    id="ApexHFTQueueReplay-v0",
    entry_point="engine.rl_trading.envs.queue_replay_env:QueueReplayEnv",
)
