"""
run.py
------
Entry point for the Flask development server.

Starts the webhook receiver on http://127.0.0.1:5000 with
Tornado queue workers and Celery integration initialised
automatically via the application factory.

Usage::

    python run.py
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5000)
