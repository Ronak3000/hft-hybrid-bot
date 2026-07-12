#!/bin/bash

# Start the Celery background worker in the background
celery -A worker.tasks.rl_training worker --loglevel=info &

# Start the FastAPI server in the foreground
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
