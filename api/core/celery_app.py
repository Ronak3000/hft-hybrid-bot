"""Compatibility import only; the removed training API never dispatches jobs."""

from worker.main import celery_app

__all__ = ["celery_app"]
