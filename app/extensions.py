"""
app/extensions.py
-----------------
Shared Flask extensions instantiated here and initialised
in the application factory (``app/__init__.py``).

Extensions:
    mongo (PyMongo): Flask-PyMongo instance providing access to the
                     MongoDB ``github_events_db`` database.
"""

from flask_pymongo import PyMongo

# Global PyMongo instance — configured via app.config["MONGO_URI"]
# and bound to the app in create_app() with mongo.init_app(app).
mongo = PyMongo()
