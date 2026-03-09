"""
app/celery_app.py
-----------------
Celery application factory.

Uses **Redis** as both the message broker and result backend.

**Why Redis over RabbitMQ?**

- **Simpler deployment**: single service (Redis) vs. RabbitMQ's more
  complex setup with Erlang runtime, management plugin, etc.
- **Dual-purpose**: acts as both broker AND result backend — no extra
  service or configuration needed.
- **Lower resource footprint**: ideal for the moderate throughput
  of webhook events in this project.
- **Excellent Docker integration**: lightweight official image
  (~30 MB), minimal configuration, fast startup.
- **Zero extra packages**: ``celery[redis]`` bundles everything needed.

Override broker / backend URLs via environment variables::

    CELERY_BROKER_URL      (default: redis://localhost:6379/0)
    CELERY_RESULT_BACKEND  (default: redis://localhost:6379/0)
"""

import os
from celery import Celery

# ── Default Redis URLs ──
_DEFAULT_BROKER = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
_DEFAULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

celery = Celery(
    "webhook_app",
    broker=_DEFAULT_BROKER,
    backend=_DEFAULT_BACKEND,
)

# ── Serialisation & timezone settings ──
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


def init_celery(app):
    """
    Bind the Celery instance to a Flask application so that tasks
    execute within the Flask application context.

    This allows tasks to access Flask-managed resources like the
    ``mongo`` database connection.

    Args:
        app (Flask): The Flask application instance.

    Returns:
        Celery: The configured Celery instance.
    """
    celery.conf.broker_url = app.config.get("CELERY_BROKER_URL", _DEFAULT_BROKER)
    celery.conf.result_backend = app.config.get("CELERY_RESULT_BACKEND", _DEFAULT_BACKEND)

    class ContextTask(celery.Task):
        """Celery Task subclass that wraps execution in the Flask app context."""

        abstract = True

        def __call__(self, *args, **kwargs):
            """Execute the task within the Flask application context."""
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery
