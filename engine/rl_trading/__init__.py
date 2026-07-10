from gymnasium.envs.registration import register

# Register the environment so it can be created via gym.make() if needed in the future
register(
    id='InstitutionalHFT-v0',
    entry_point='rl_trading.envs.trading_env:TradingEnv',
)