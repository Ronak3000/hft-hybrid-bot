"""Optional compatibility worker: old event-generation jobs are rejected."""

import os
from celery import Celery

broker = os.getenv("CELERY_BROKER_URL")
backend = os.getenv("CELERY_RESULT_BACKEND")
if not broker or not backend:
    raise RuntimeError("Set CELERY_BROKER_URL and CELERY_RESULT_BACKEND; no embedded credentials are used.")

celery_app = Celery("apexhft_retired_jobs", broker=broker, backend=backend,
                    include=["worker.tasks.rl_training"])
celery_app.conf.update(task_serializer="json", accept_content=["json"],
                       result_serializer="json", task_track_started=True,
                       worker_prefetch_multiplier=1, timezone="UTC")
