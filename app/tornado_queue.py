"""
app/tornado_queue.py
--------------------
Tornado-based asynchronous queue for concurrent webhook processing.

Uses ``tornado.queues.Queue`` to manage multiple worker coroutines that
process incoming webhook events concurrently in a background thread.

Reference: https://www.tornadoweb.org/en/stable/guide/queues.html

Architecture:
    1. Flask request handler enqueues parsed event data via ``enqueue()``.
    2. Multiple Tornado worker coroutines consume items from the queue.
    3. Each worker dispatches a Celery task for persistent storage.
    4. The Tornado IOLoop runs in a dedicated daemon thread, keeping
       the Flask request–response cycle fast and non-blocking.
"""

import asyncio
import logging
import threading

from tornado.ioloop import IOLoop
from tornado.queues import Queue

logger = logging.getLogger(__name__)

# ── Module-level state ──
_queue = Queue(maxsize=100)
_loop = None
_initialized = False


async def _process_item(item):
    """
    Process a single webhook event from the queue.

    Dispatches the event data to the ``store_event`` Celery task
    for asynchronous, persistent storage in MongoDB.

    Args:
        item (dict): Parsed webhook event data containing keys like
                     ``request_id``, ``action``, ``author``, etc.
    """
    from app.tasks import store_event

    request_id = item.get("request_id", "unknown")
    action = item.get("action", "unknown")

    try:
        store_event.delay(item)
        logger.info(
            "Dispatched Celery task: action=%s, request_id=%s",
            action, request_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to dispatch Celery task (request_id=%s): %s",
            request_id, exc,
        )


async def _worker(worker_id):
    """
    Tornado queue worker coroutine.

    Continuously pulls items from the shared queue and processes them.
    Runs indefinitely until the IOLoop is stopped.

    Args:
        worker_id (int): Identifier for this worker (used in log messages).
    """
    logger.info("Tornado worker-%d started", worker_id)
    while True:
        item = await _queue.get()
        try:
            await _process_item(item)
        except Exception as exc:
            logger.error("Worker-%d unhandled error: %s", worker_id, exc)
        finally:
            _queue.task_done()


def _run_loop(num_workers):
    """
    Entry point for the background thread.

    Creates a new asyncio event loop, starts the Tornado IOLoop,
    spawns the requested number of worker coroutines, and runs
    the loop indefinitely.

    Args:
        num_workers (int): Number of concurrent worker coroutines to spawn.
    """
    global _loop

    asyncio.set_event_loop(asyncio.new_event_loop())
    _loop = IOLoop.current()

    for i in range(num_workers):
        _loop.spawn_callback(_worker, i)

    logger.info("Tornado IOLoop starting with %d workers", num_workers)
    _loop.start()


def enqueue(item):
    """
    Thread-safe enqueue of a webhook event into the Tornado queue.

    Called from Flask request handlers running in the main thread.
    Uses ``IOLoop.add_callback`` to safely interact with the Tornado
    IOLoop from another thread.

    Args:
        item (dict): Parsed webhook event data to be processed.

    Returns:
        bool: ``True`` if the item was enqueued successfully,
              ``False`` if the queue is not initialised.
    """
    if _loop is None:
        logger.warning("Tornado queue not initialised — item not enqueued")
        return False

    _loop.add_callback(_queue.put, item)
    logger.debug(
        "Enqueued event: request_id=%s", item.get("request_id", "unknown")
    )
    return True


def init_tornado_workers(num_workers=3):
    """
    Initialise Tornado queue workers in a background daemon thread.

    This function should be called once during application startup
    (from ``create_app()``).  The daemon thread is automatically
    terminated when the main process exits.

    Args:
        num_workers (int): Number of concurrent worker coroutines
                           (default: 3).
    """
    global _initialized

    if _initialized:
        logger.warning("Tornado workers already initialised — skipping")
        return

    thread = threading.Thread(
        target=_run_loop,
        args=(num_workers,),
        daemon=True,
        name="tornado-queue-workers",
    )
    thread.start()
    _initialized = True
    logger.info(
        "Tornado queue workers initialised: %d workers in thread '%s'",
        num_workers, thread.name,
    )
