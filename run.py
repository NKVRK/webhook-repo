"""
run.py
------
Entry point for the Flask development server.
Starts the webhook receiver on http://127.0.0.1:5000.

Usage:
    python run.py
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
