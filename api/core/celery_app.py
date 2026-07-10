from celery import Celery

# Initialize Celery to use Redis as both the message broker and the result backend
celery_app = Celery(
    "quant_tasks",
    broker="rediss://default:gQAAAAAAAnkDAAIgcDFhYzc2ZjFiZjNkOTk0NmVmYmJkZmY0OGEwODNhNTdhOA@suitable-rooster-162051.upstash.io:6379?ssl_cert_reqs=CERT_NONE",
    backend="rediss://default:gQAAAAAAAnkDAAIgcDFhYzc2ZjFiZjNkOTk0NmVmYmJkZmY0OGEwODNhNTdhOA@suitable-rooster-162051.upstash.io:6379?ssl_cert_reqs=CERT_NONE"
)

# Standardize the serialization to JSON for safe cross-process communication
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Prevent memory leaks by forcing workers to restart after 100 heavy RL jobs
    worker_max_tasks_per_child=100 
)