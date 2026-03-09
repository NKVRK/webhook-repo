"""
celery_worker.py
----------------
Entry point for running the Celery worker process.

Usage::

    celery -A celery_worker.celery worker --loglevel=info

This module creates the Flask app (to initialise extensions and config),
then exposes the ``celery`` instance for the Celery CLI to discover tasks.
"""

from app import create_app
from app.celery_app import celery  # noqa: F401 — imported for Celery CLI discovery

# Create the Flask app so extensions (Mongo, Celery binding, etc.) are initialised.
app = create_app()
