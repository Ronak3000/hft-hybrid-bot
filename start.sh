#!/bin/bash

# No legacy candle-generated event worker is started.
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --no-proxy-headers
