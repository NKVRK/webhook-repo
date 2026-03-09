"""
app/tasks.py
------------
Celery task definitions for asynchronous webhook event processing.

Tasks:
    store_event — Validates and persists a webhook event to MongoDB.
                  Idempotent: silently skips duplicates using the
                  unique compound index on (request_id, action).
"""

import logging

from pymongo.errors import DuplicateKeyError

from app.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(bind=True, max_retries=3, default_retry_delay=5)
def store_event(self, event_data):
    """
    Store a parsed webhook event document in MongoDB.

    This task is idempotent: if a duplicate event (same ``request_id``
    + ``action``) already exists, the insert is silently skipped
    thanks to the unique compound index.

    Args:
        event_data (dict): Parsed event with keys: ``request_id``,
                           ``author``, ``action``, ``from_branch``,
                           ``to_branch``, ``timestamp``.

    Returns:
        dict: Status of the operation with keys ``status`` and
              ``request_id``.

    Raises:
        self.retry: On unexpected database errors (up to 3 retries
                    with 5-second delay).
    """
    from app.extensions import mongo  # deferred import to avoid circular refs

    request_id = event_data.get("request_id", "unknown")
    action = event_data.get("action", "unknown")

    try:
        mongo.db.events.insert_one(event_data)
        logger.info(
            "Event stored via Celery: action=%s, request_id=%s",
            action, request_id,
        )
        return {"status": "stored", "request_id": request_id}

    except DuplicateKeyError:
        logger.info(
            "Duplicate event skipped (Celery): action=%s, request_id=%s",
            action, request_id,
        )
        return {"status": "duplicate", "request_id": request_id}

    except Exception as exc:
        logger.error(
            "Failed to store event (request_id=%s): %s", request_id, exc,
        )
        raise self.retry(exc=exc)
