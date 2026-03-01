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
    """
    doc["_id"] = str(doc["_id"])
    return doc


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
    payload = request.json
    event_type = request.headers.get("X-GitHub-Event", "")

    # ---- Ping event (sent when webhook is first created) ----
    if event_type == "ping":
        return jsonify({"status": "pong"}), 200

    # ---- PUSH event ----
    if event_type == "push":
        head_commit = payload.get("head_commit")

        # GitHub may send a push with no commits (e.g. branch deletion)
        if head_commit is None:
            return jsonify({"status": "ignored", "reason": "no head_commit"}), 200

        event = {
            "request_id": head_commit["id"],                       # commit SHA
            "author":     payload["pusher"]["name"],               # pusher username
            "action":     "PUSH",
            "from_branch": payload["ref"].replace("refs/heads/", ""),
            "to_branch":   payload["ref"].replace("refs/heads/", ""),
            "timestamp":  _parse_timestamp(head_commit["timestamp"]),
        }

    # ---- PULL REQUEST / MERGE event ----
    elif event_type == "pull_request":
        pr = payload["pull_request"]
        pr_action = payload.get("action", "")

        # Determine the webhook action we care about
        if pr_action == "closed" and pr.get("merged") is True:
            action = "MERGE"
            ts_raw = pr["merged_at"]                              # merge timestamp
        elif pr_action in ("opened", "reopened"):
            action = "PULL_REQUEST"
            ts_raw = pr["created_at"]                             # PR creation time
        else:
            # Other sub-actions (edited, labeled, …) – acknowledge but skip
            return jsonify({"status": "ignored", "reason": f"PR action '{pr_action}' not tracked"}), 200

        event = {
            "request_id":  str(pr["number"]),                     # PR number
            "author":      pr["user"]["login"],                   # PR author
            "action":      action,
            "from_branch": pr["head"]["ref"],                     # source branch
            "to_branch":   pr["base"]["ref"],                     # target branch
            "timestamp":   _parse_timestamp(ts_raw),
        }

    else:
        # Unsupported event type – acknowledge silently
        return jsonify({"status": "ignored", "reason": f"event '{event_type}' not tracked"}), 200

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
