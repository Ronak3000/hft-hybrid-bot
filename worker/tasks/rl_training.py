"""Reject stale queued jobs instead of recreating the removed event generator."""

from celery import shared_task


@shared_task(name="worker.tasks.rl_training.train_ppo_model")
def train_ppo_model(*args, **kwargs):
    raise RuntimeError(
        "Legacy synthetic-event training has been removed. "
        "Train only with scripts/train_queue_ppo.py and validated Binance captures."
    )
