import os
from celery import Celery

# Ensure the worker can find the tasks directory
os.environ.setdefault('FORKED_BY_MULTIPROCESSING', '1')

celery_app = Celery(
    "quant_worker",
    broker="rediss://default:gQAAAAAAAnkDAAIgcDFhYzc2ZjFiZjNkOTk0NmVmYmJkZmY0OGEwODNhNTdhOA@suitable-rooster-162051.upstash.io:6379?ssl_cert_reqs=CERT_NONE",
    backend="rediss://default:gQAAAAAAAnkDAAIgcDFhYzc2ZjFiZjNkOTk0NmVmYmJkZmY0OGEwODNhNTdhOA@suitable-rooster-162051.upstash.io:6379?ssl_cert_reqs=CERT_NONE",
    include=["tasks.rl_training"] # Tells Celery where to look for jobs
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    worker_prefetch_multiplier=1, # Only grab one heavy ML job at a time
    task_track_started=True
)