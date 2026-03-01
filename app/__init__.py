"""
app/__init__.py
---------------
Flask application factory.
Creates and configures the Flask app, initialises extensions,
and registers blueprints.
"""

import os

from flask import Flask
from flask_cors import CORS

from app.extensions import mongo
from app.webhook.routes import webhook

# Default MongoDB Atlas connection string (override via MONGO_URI env var)
_DEFAULT_MONGO_URI = (
    "mongodb+srv://nakkaramakrishna9999_db_user:e9XvsNqenSBPfEpx"
    "@webhookcluster.iv0kufi.mongodb.net/github_events_db"
    "?retryWrites=true&w=majority&appName=WebhookCluster"
)


def create_app():
    """Create and configure the Flask application."""

    app = Flask(__name__)

    # --------------- Configuration ---------------
    # Prefer MONGO_URI from environment; fall back to default for local dev.
    app.config["MONGO_URI"] = os.environ.get("MONGO_URI", _DEFAULT_MONGO_URI)

    # --------------- Extensions ---------------
    mongo.init_app(app)          # Bind PyMongo to this app
    CORS(app)                    # Allow cross-origin requests (React dev server)

    # --------------- Blueprints ---------------
    app.register_blueprint(webhook)

    # --------------- Database Indexes ---------------
    # Ensure indexes exist for efficient queries (idempotent).
    with app.app_context():
        _ensure_indexes()

    return app


def _ensure_indexes():
    """
    Create MongoDB indexes if they don't already exist.

    - Compound unique index on (request_id, action) → enforces the
      duplicate guard at the database level and speeds up lookups.
    - Index on timestamp → speeds up the incremental polling query.
    """
    mongo.db.events.create_index(
        [("request_id", 1), ("action", 1)],
        unique=True,
        name="idx_request_action_unique",
    )
    mongo.db.events.create_index(
        [("timestamp", -1)],
        name="idx_timestamp_desc",
    )
