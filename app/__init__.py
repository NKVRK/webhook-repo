"""
app/__init__.py
---------------
Flask application factory.

Creates and configures the Flask app, initialises extensions,
registers blueprints, and sets up logging, Celery with Redis,
and Tornado queue workers for concurrent processing.
"""

import logging
import os

from flask import Flask
from flask_cors import CORS

from app.extensions import mongo
from app.logging_config import setup_logging
from app.celery_app import init_celery
from app.tornado_queue import init_tornado_workers
from app.webhook.routes import webhook

logger = logging.getLogger(__name__)

# Default MongoDB Atlas connection string (override via MONGO_URI env var)
_DEFAULT_MONGO_URI = (
    "mongodb+srv://nakkaramakrishna9999_db_user:e9XvsNqenSBPfEpx"
    "@webhookcluster.iv0kufi.mongodb.net/github_events_db"
    "?retryWrites=true&w=majority&appName=WebhookCluster"
)


def create_app():
    """
    Create and configure the Flask application.

    Initialises (in order):
      1. File-based logging (``logs/app.log``)
      2. MongoDB via PyMongo
      3. CORS for cross-origin requests from the React dev server
      4. Celery with Redis broker for async task processing
      5. Tornado queue workers for concurrent webhook handling
      6. Webhook blueprint (routes)
      7. MongoDB indexes for efficient queries

    Returns:
        Flask: The fully configured Flask application instance.
    """
    app = Flask(__name__)

    # --------------- Configuration ---------------
    app.config["MONGO_URI"] = os.environ.get("MONGO_URI", _DEFAULT_MONGO_URI)
    app.config["CELERY_BROKER_URL"] = os.environ.get(
        "CELERY_BROKER_URL", "redis://localhost:6379/0"
    )
    app.config["CELERY_RESULT_BACKEND"] = os.environ.get(
        "CELERY_RESULT_BACKEND", "redis://localhost:6379/0"
    )

    # --------------- Logging ---------------
    setup_logging(app)

    # --------------- Extensions ---------------
    try:
        mongo.init_app(app)
        logger.info("MongoDB connection initialised")
    except Exception as exc:
        logger.error("Failed to initialise MongoDB: %s", exc)
        raise

    CORS(app)
    logger.info("CORS enabled")

    # --------------- Celery ---------------
    try:
        init_celery(app)
        logger.info("Celery initialised with Redis broker")
    except Exception as exc:
        logger.warning(
            "Celery initialisation failed (tasks will fall back to "
            "synchronous storage): %s", exc,
        )

    # --------------- Tornado Queue Workers ---------------
    try:
        init_tornado_workers(num_workers=3)
    except Exception as exc:
        logger.warning("Tornado workers failed to start: %s", exc)

    # --------------- Blueprints ---------------
    app.register_blueprint(webhook)
    logger.info("Webhook blueprint registered")

    # --------------- Database Indexes ---------------
    with app.app_context():
        _ensure_indexes()

    logger.info("Application factory complete — app ready")
    return app


def _ensure_indexes():
    """
    Create MongoDB indexes if they don't already exist.

    Indexes created:
      - Compound unique index on ``(request_id, action)`` — enforces the
        duplicate guard at the database level and speeds up lookups.
      - Descending index on ``timestamp`` — speeds up the incremental
        polling query used by the frontend.

    Raises:
        Exception: Logs and re-raises any MongoDB connection or index
                   creation errors.
    """
    try:
        mongo.db.events.create_index(
            [("request_id", 1), ("action", 1)],
            unique=True,
            name="idx_request_action_unique",
        )
        mongo.db.events.create_index(
            [("timestamp", -1)],
            name="idx_timestamp_desc",
        )
        logger.info("MongoDB indexes ensured successfully")
    except Exception as exc:
        logger.error("Failed to create MongoDB indexes: %s", exc)
        raise
