"""
app/logging_config.py
---------------------
Configures file-based and console logging for the application.

Log format:  timestamp | level | module | message
Log file:    logs/app.log (with rotation at 5 MB, up to 5 backups)
"""

import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(app=None, log_level=logging.INFO):
    """
    Configure application-wide logging with file and console handlers.

    Creates a ``logs/`` directory at the project root (if it doesn't
    exist) and writes rotating log files there.

    Args:
        app (Flask, optional):  Flask app instance.  If provided, the
                                Flask logger is also wired to the same
                                handlers.
        log_level (int):        Minimum logging level (default: ``INFO``).

    Returns:
        None
    """
    # ── Ensure logs directory exists ──
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "app.log")

    # ── Format: timestamp | level | module | message ──
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(module)-20s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Rotating file handler (5 MB max, 5 backups) ──
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    # ── Console handler ──
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    # ── Configure root logger (avoid duplicate handlers on reload) ──
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    if not root_logger.handlers:
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    # ── Wire Flask app logger ──
    if app:
        app.logger.setLevel(log_level)
        app.logger.handlers = []
        app.logger.addHandler(file_handler)
        app.logger.addHandler(console_handler)
        app.logger.propagate = False
        app.logger.info("Logging configured — file: %s", log_file)
