"""Validated user controls; fixed schema/venue identities cannot be overridden."""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class PPOSettings(Settings):
    learning_rate: float = Field(0.0003, gt=0, le=0.1, description="Optimizer step size")
    n_steps: int = Field(2048, ge=2, le=65536, description="Rollout steps before each update")
    batch_size: int = Field(64, ge=2, le=65536, description="Samples per gradient batch; must divide rollout")
    n_epochs: int = Field(10, ge=1, le=100, description="Passes over each rollout")
    gamma: float = Field(0.99, gt=0, le=1, description="Discount factor")
    gae_lambda: float = Field(0.95, gt=0, le=1, description="Advantage-estimation decay")
    clip_range: float = Field(0.2, gt=0, le=1, description="Policy update clipping")
    clip_range_vf: float | None = Field(None, gt=0, le=1000, description="Value clipping; blank disables")
    entropy_coefficient: float = Field(0.0, ge=0, le=1, description="Exploration bonus")
    value_coefficient: float = Field(0.5, gt=0, le=10, description="Value loss weight")
    max_grad_norm: float = Field(0.5, gt=0, le=100, description="Gradient norm cap")
    target_kl: float | None = Field(None, gt=0, le=1, description="Early-stop update KL threshold; blank disables")
    normalize_advantage: bool = Field(True, description="Normalize advantages within updates")
    hidden_width: int = Field(64, ge=8, le=512, description="Units per shared-size actor/critic hidden layer")
    hidden_layers: int = Field(2, ge=1, le=4, description="Number of hidden layers")
    activation: Literal["tanh", "relu"] = Field("tanh", description="Network activation")
    orthogonal_init: bool = Field(True, description="Orthogonal network initialization")
    seed: int = Field(7, ge=0, le=2147483647, description="Random seed")
    torch_threads: int = Field(1, ge=1, le=16, description="CPU threads (bounded for shared host)")
    device: Literal["cpu", "auto", "cuda"] = Field("cpu", description="Training device; CUDA requires a capable host")

    @model_validator(mode="after")
    def batches(self):
        if self.n_steps % self.batch_size:
            raise ValueError("Batch size must divide rollout steps.")
        return self


class SimulationSettings(Settings):
    quantity: float = Field(0.001, gt=0, le=10, description="BTC quantity per quote")
    initial_cash: float = Field(1000000, gt=0, le=1e9, description="Starting paper cash in USDT")
    max_abs_inventory: float = Field(0.01, gt=0, le=100, description="Maximum absolute BTC inventory")
    maker_fee_rate: float = Field(0, ge=0, le=0.01, description="Fee as decimal fraction; zero means a fee-free experiment")
    order_latency_ns: int = Field(1000000, ge=0, le=10**10, description="Simulated order latency (nanoseconds)")
    cancel_latency_ns: int = Field(1000000, ge=0, le=10**10, description="Simulated cancel latency (nanoseconds)")
    decision_interval_ns: int = Field(1000000000, ge=100000000, le=60 * 10**9, description="Policy decision spacing (nanoseconds)")
    reward_scale: float = Field(1, gt=0, le=1e6, description="Divide P&L reward by this scale")
    inventory_penalty_per_second: float = Field(0, ge=0, le=1e6, description="Penalty on squared inventory ratio per second")
    half_spread_tick_choices: list[int] = Field([1,100,1000,8000,10000], min_length=1, max_length=32, description="Distinct positive half-spread widths in ticks")
    max_absolute_skew_ticks: int = Field(2, ge=0, le=10000, description="Maximum inventory/price skew in ticks")
    entry_fee_buffer_bps: float | None = Field(None, ge=0, le=1000, description="Entry cost guard buffer; blank disables")

    @model_validator(mode="after")
    def limits(self):
        widths = self.half_spread_tick_choices
        if widths != sorted(set(widths)) or any(not 1 <= n <= 1000000 for n in widths):
            raise ValueError("Spread widths must be unique, ascending integers between 1 and 1000000.")
        if self.quantity > self.max_abs_inventory:
            raise ValueError("Quote quantity cannot exceed the inventory cap.")
        return self


def command_options(ppo, simulation):
    options = []
    for key, value in {**ppo.model_dump(), **simulation.model_dump()}.items():
        if value is None:
            continue
        flag = "--" + key.replace("_", "-")
        if isinstance(value, bool):
            options.append(flag if value else "--no-" + key.replace("_", "-"))
        elif isinstance(value, list):
            options.extend([flag, *map(str, value)])
        else:
            options.extend([flag, str(value)])
    return options
