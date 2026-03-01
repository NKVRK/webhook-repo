"""
app/__init__.py
---------------
Flask application factory.
Creates and configures the Flask app, initialises extensions,
and registers blueprints.
"""

from flask import Flask
from flask_cors import CORS

from app.extensions import mongo
from app.webhook.routes import webhook


def create_app():
    """Create and configure the Flask application."""

    app = Flask(__name__)

    # --------------- Configuration ---------------
    # MongoDB Atlas connection string (database: github_events_db)
    app.config["MONGO_URI"] = (
        "mongodb+srv://nakkaramakrishna9999_db_user:e9XvsNqenSBPfEpx"
        "@webhookcluster.iv0kufi.mongodb.net/github_events_db"
        "?retryWrites=true&w=majority&appName=WebhookCluster"
    )

    # --------------- Extensions ---------------
    mongo.init_app(app)          # Bind PyMongo to this app
    CORS(app)                    # Allow cross-origin requests (React dev server)

    # --------------- Blueprints ---------------
    app.register_blueprint(webhook)

    return app
