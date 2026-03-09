"""
webhook/routes.py
-----------------
Blueprint that exposes:

  POST /webhook/receiver   – GitHub webhook endpoint (receives push / PR events)
  GET  /webhook/events     – Returns new events after a given timestamp (polling)
  GET  /webhook/events/all – Returns every stored event (initial page load)

Events received via the webhook are enqueued into a Tornado queue for
concurrent processing, then dispatched as Celery tasks for persistent
storage in MongoDB.  If the async pipeline is unavailable, events are
stored directly as a fallback.
"""

import logging
from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, request

from app.extensions import mongo
from app.tornado_queue import enqueue

logger = logging.getLogger(__name__)

# --------------- Blueprint ---------------
webhook = Blueprint("Webhook", __name__, url_prefix="/webhook")


# ==================== helpers ====================

def _parse_timestamp(raw: str) -> str:
    """
    Convert a GitHub-supplied timestamp string into a
    UTC ISO-8601 string (e.g. ``'2026-03-01T14:30:00Z'``).

    GitHub sends timestamps in ISO-8601 format, sometimes with
    a timezone offset (e.g. ``'2026-03-01T14:30:00+05:30'``) or
    with a trailing ``'Z'`` for UTC.

    Args:
        raw (str): Raw timestamp string from the GitHub payload.

    Returns:
        str: Normalised UTC timestamp in ``YYYY-MM-DDTHH:MM:SSZ`` format.

    Raises:
        ValueError: If the timestamp string cannot be parsed.
    """
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError) as exc:
        logger.error("Failed to parse timestamp '%s': %s", raw, exc)
        raise


def _serialize_event(doc: dict) -> dict:
    """
    Convert a MongoDB document into a JSON-safe dictionary
    by turning the ObjectId ``_id`` into a plain string.

    Args:
        doc (dict): A MongoDB document with an ``_id`` field.

    Returns:
        dict: A shallow copy of the document with ``_id`` as a string.
    """
    serialized = {**doc, "_id": str(doc["_id"])}
    return serialized


def _store_event_direct(event):
    """
    Directly store an event in MongoDB (fallback when the async
    pipeline — Tornado queue + Celery — is unavailable).

    Skips duplicates using a ``find_one`` check before insertion.

    Args:
        event (dict): Parsed event data to store.

    Raises:
        Exception: On MongoDB insertion errors (except duplicates).
    """
    try:
        existing = mongo.db.events.find_one({
            "request_id": event["request_id"],
            "action": event["action"],
        })
        if existing:
            logger.info(
                "Duplicate event (direct): action=%s, request_id=%s",
                event["action"], event["request_id"],
            )
            return

        mongo.db.events.insert_one(event)
        logger.info(
            "Event stored directly: action=%s, request_id=%s",
            event["action"], event["request_id"],
        )
    except Exception as exc:
        logger.error("Direct storage failed: %s", exc)
        raise


# ==================== routes ====================

@webhook.route("/receiver", methods=["POST"])
def receiver():
    """
    Receive a GitHub webhook event, parse it, and enqueue it
    for asynchronous processing via Tornado queue and Celery.

    Supported GitHub event types (via ``X-GitHub-Event`` header):
      - ``push``          → stored as action ``PUSH``
      - ``pull_request``  → stored as ``PULL_REQUEST`` or ``MERGE``

    Returns:
        tuple: JSON response and HTTP status code.
            - 200 with ``status: "ok"`` on success.
            - 200 with ``status: "ignored"`` for untracked events.
            - 200 with ``status: "pong"`` for ping events.
            - 400 for malformed payloads.
            - 500 for unexpected server errors.
    """
    try:
        # ---- Validate incoming request ----
        payload = request.json
        if payload is None:
            logger.warning("Received non-JSON request body")
            return jsonify({"status": "error", "reason": "Request body must be JSON"}), 400

        event_type = request.headers.get("X-GitHub-Event", "")
        logger.info("Received webhook: event_type=%s", event_type)

        # ---- Ping event (sent when webhook is first created) ----
        if event_type == "ping":
            logger.info("Ping event received — responding with pong")
            return jsonify({"status": "pong"}), 200

        # ---- Parse the event inside a try/except for safety ----
        try:
            event = _parse_event(payload, event_type)
        except ValueError as exc:
            # Expected skip (untracked action) — not an error
            logger.info("Event ignored: %s", exc)
            return jsonify({"status": "ignored", "reason": str(exc)}), 200
        except (KeyError, TypeError) as exc:
            # Malformed payload — return a clear 400 instead of a 500
            logger.warning("Malformed payload: %s", exc)
            return jsonify({"status": "error", "reason": f"Malformed payload: {exc}"}), 400

        if event is None:
            logger.info("No actionable data in event")
            return jsonify({"status": "ignored", "reason": "no actionable data"}), 200

        # ---- Enqueue for async processing via Tornado queue → Celery ----
        enqueued = enqueue(event)
        if enqueued:
            logger.info(
                "Event enqueued for async processing: action=%s, request_id=%s",
                event["action"], event["request_id"],
            )
        else:
            # Fallback: store directly if Tornado queue is unavailable
            logger.warning("Tornado queue unavailable — storing event directly")
            _store_event_direct(event)

        return jsonify({
            "status": "ok",
            "action": event["action"],
            "request_id": event["request_id"],
        }), 200

    except Exception as exc:
        logger.exception("Unexpected error in receiver: %s", exc)
        return jsonify({"status": "error", "reason": "Internal server error"}), 500


def _parse_event(payload: dict, event_type: str) -> dict | None:
    """
    Extract a normalised event dict from a GitHub webhook payload.

    Args:
        payload (dict):    The decoded JSON body from GitHub.
        event_type (str):  Value of the ``X-GitHub-Event`` header.

    Returns:
        dict or None: A dict ready for MongoDB insertion, or ``None``
                      if the event should be silently ignored.

    Raises:
        ValueError:  When the event sub-action is not tracked
                     (e.g. PR edited, labeled, etc.).
        KeyError:    When the payload is missing expected fields.
        TypeError:   When payload fields have unexpected types.
    """
    # ---- PUSH event ----
    if event_type == "push":
        head_commit = payload.get("head_commit")

        # GitHub may send a push with no commits (e.g. branch deletion)
        if head_commit is None:
            logger.debug("Push event with no head_commit (e.g. branch deletion)")
            return None

        branch = payload["ref"].replace("refs/heads/", "")

        return {
            "request_id":  head_commit["id"],            # commit SHA
            "author":      payload["pusher"]["name"],    # pusher username
            "action":      "PUSH",
            "from_branch": branch,
            "to_branch":   branch,
            "timestamp":   _parse_timestamp(head_commit["timestamp"]),
        }

    # ---- PULL REQUEST / MERGE event ----
    if event_type == "pull_request":
        pr = payload["pull_request"]
        pr_action = payload.get("action", "")

        # Determine the webhook action we care about
        if pr_action == "closed" and pr.get("merged") is True:
            action = "MERGE"
            ts_raw = pr["merged_at"]                     # merge timestamp
        elif pr_action in ("opened", "reopened"):
            action = "PULL_REQUEST"
            ts_raw = pr["created_at"]                    # PR creation time
        else:
            # Other sub-actions (edited, labeled, …) – not tracked
            raise ValueError(f"PR action '{pr_action}' not tracked")

        return {
            "request_id":  str(pr["number"]),             # PR number
            "author":      pr["user"]["login"],           # PR author
            "action":      action,
            "from_branch": pr["head"]["ref"],             # source branch
            "to_branch":   pr["base"]["ref"],             # target branch
            "timestamp":   _parse_timestamp(ts_raw),
        }

    # Unsupported event type
    raise ValueError(f"event '{event_type}' not tracked")


@webhook.route("/events", methods=["GET"])
def get_new_events():
    """
    Return events whose timestamp is strictly after the
    ``after`` query parameter.

    Used by the UI for 15-second incremental polling so
    already-displayed events are skipped.

    Query params:
        after (str): ISO-8601 UTC string (e.g. ``'2026-03-01T14:30:00Z'``).

    Returns:
        tuple: JSON response containing a list of events, and HTTP status code.
    """
    try:
        after = request.args.get("after")

        if after:
            logger.debug("Polling for events after: %s", after)
            cursor = mongo.db.events.find(
                {"timestamp": {"$gt": after}}
            ).sort("timestamp", -1)
        else:
            logger.debug("No 'after' param — returning all events")
            cursor = mongo.db.events.find().sort("timestamp", -1)

        events = [_serialize_event(doc) for doc in cursor]
        logger.debug("Returning %d event(s)", len(events))
        return jsonify({"events": events}), 200

    except Exception as exc:
        logger.exception("Error fetching new events: %s", exc)
        return jsonify({"status": "error", "reason": "Failed to fetch events"}), 500


@webhook.route("/events/all", methods=["GET"])
def get_all_events():
    """
    Return stored events from the last 15 minutes, sorted newest-first.

    Called on initial page load and on each poll cycle to show only
    the most recent 15-minute window of event data.

    Returns:
        tuple: JSON response containing a list of events, and HTTP status code.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        logger.debug("Fetching all events since: %s", cutoff_str)

        cursor = mongo.db.events.find(
            {"timestamp": {"$gte": cutoff_str}}
        ).sort("timestamp", -1)

        events = [_serialize_event(doc) for doc in cursor]
        logger.info("Initial load: returning %d event(s)", len(events))
        return jsonify({"events": events}), 200

    except Exception as exc:
        logger.exception("Error fetching all events: %s", exc)
        return jsonify({"status": "error", "reason": "Failed to fetch events"}), 500
