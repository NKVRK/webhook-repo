"""
webhook/routes.py
-----------------
Blueprint that exposes:
  POST /webhook/receiver   – GitHub webhook endpoint (receives push / PR events)
  GET  /webhook/events     – Returns new events after a given timestamp (polling)
  GET  /webhook/events/all – Returns every stored event (initial page load)
"""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.extensions import mongo

# --------------- Blueprint ---------------
webhook = Blueprint("Webhook", __name__, url_prefix="/webhook")


# ==================== helpers ====================

def _parse_timestamp(raw: str) -> str:
    """
    Convert a GitHub-supplied timestamp string into a
    UTC ISO-8601 string (e.g. '2026-03-01T14:30:00Z').

    GitHub sends timestamps in ISO-8601 format, sometimes with
    a timezone offset (e.g. '2026-03-01T14:30:00+05:30') or
    with a trailing 'Z' for UTC.
    """
    # fromisoformat() handles offsets natively in Python 3.11+
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    # Normalise to UTC and return as a clean ISO string
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _serialize_event(doc: dict) -> dict:
    """
    Convert a MongoDB document into a JSON-safe dictionary
    by turning the ObjectId ``_id`` into a plain string.

    Returns a shallow copy so the original cursor document
    is never mutated.
    """
    serialized = {**doc, "_id": str(doc["_id"])}
    return serialized


# ==================== routes ====================

@webhook.route("/receiver", methods=["POST"])
def receiver():
    """
    Receive a GitHub webhook event, parse it, and store
    the relevant data in MongoDB.

    Supported GitHub event types (via ``X-GitHub-Event`` header):
      • push          → stored as action "PUSH"
      • pull_request  → stored as "PULL_REQUEST" or "MERGE"
    """
    # ---- Validate incoming request ----
    payload = request.json
    if payload is None:
        return jsonify({"status": "error", "reason": "Request body must be JSON"}), 400

    event_type = request.headers.get("X-GitHub-Event", "")

    # ---- Ping event (sent when webhook is first created) ----
    if event_type == "ping":
        return jsonify({"status": "pong"}), 200

    # ---- Parse the event inside a try/except for safety ----
    try:
        event = _parse_event(payload, event_type)
    except ValueError as exc:
        # Expected skip (untracked action) — not an error
        return jsonify({"status": "ignored", "reason": str(exc)}), 200
    except (KeyError, TypeError) as exc:
        # Malformed payload — return a clear 400 instead of a 500
        return jsonify({"status": "error", "reason": f"Malformed payload: {exc}"}), 400

    if event is None:
        return jsonify({"status": "ignored", "reason": "no actionable data"}), 200

    # ---- Duplicate guard: skip if this (request_id, action) already exists ----
    existing = mongo.db.events.find_one({
        "request_id": event["request_id"],
        "action":     event["action"],
    })
    if existing:
        return jsonify({"status": "duplicate", "request_id": event["request_id"]}), 200

    # ---- Insert into MongoDB ----
    mongo.db.events.insert_one(event)

    return jsonify({"status": "ok", "action": event["action"], "request_id": event["request_id"]}), 200


def _parse_event(payload: dict, event_type: str) -> dict | None:
    """
    Extract a normalised event dict from a GitHub webhook payload.

    Args:
        payload:    The decoded JSON body from GitHub.
        event_type: Value of the ``X-GitHub-Event`` header.

    Returns:
        A dict ready for MongoDB insertion, or ``None`` if the
        event should be silently ignored.

    Raises:
        ValueError: When the event sub-action is not tracked
                    (e.g. PR edited, labeled, etc.).
        KeyError / TypeError: When the payload is missing
                              expected fields.
    """
    # ---- PUSH event ----
    if event_type == "push":
        head_commit = payload.get("head_commit")

        # GitHub may send a push with no commits (e.g. branch deletion)
        if head_commit is None:
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
    ``after`` query parameter.  Used by the UI for 15-second
    incremental polling so already-displayed events are skipped.

    Query params:
      after  – ISO-8601 UTC string (e.g. '2026-03-01T14:30:00Z')
    """
    after = request.args.get("after")

    if after:
        cursor = mongo.db.events.find(
            {"timestamp": {"$gt": after}}
        ).sort("timestamp", -1)
    else:
        # No cursor anchor – fall back to returning everything
        cursor = mongo.db.events.find().sort("timestamp", -1)

    events = [_serialize_event(doc) for doc in cursor]
    return jsonify({"events": events}), 200


@webhook.route("/events/all", methods=["GET"])
def get_all_events():
    """
    Return every stored event, sorted newest-first.
    Called once on initial page load.
    """
    cursor = mongo.db.events.find().sort("timestamp", -1)
    events = [_serialize_event(doc) for doc in cursor]
    return jsonify({"events": events}), 200
