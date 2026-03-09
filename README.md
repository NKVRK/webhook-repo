# GitHub Webhook Receiver

A Flask-based webhook receiver that captures **Push**, **Pull Request**, and **Merge** events from a GitHub repository, stores them in MongoDB Atlas, and displays them in a real-time React dashboard that polls every 15 seconds.

---

## Architecture

```
GitHub (action-repo)
    │
    │  Webhook (POST)
    ▼
Flask Backend (webhook-repo)
    │
    │  Enqueue
    ▼
Tornado Queue (concurrent workers)
    │
    │  Dispatch task
    ▼
Celery + Redis (async task processing)
    │
    │  Store event
    ▼
MongoDB Atlas (github_events_db)
    │
    │  Poll every 15s
    ▼
React Frontend (webhook-repo/frontend)
```

| Component | Tech Stack |
|---|---|
| **Backend** | Python 3.12, Flask, Flask-PyMongo |
| **Database** | MongoDB Atlas (cloud) / MongoDB 7 (Docker) |
| **Task Queue** | Celery 5.x with Redis broker |
| **Concurrency** | Tornado IOLoop + Queue (multithreaded workers) |
| **Frontend** | React 19, Vite 7, TailwindCSS v4 |
| **Containerisation** | Docker, Docker Compose |
| **Tunnel** | ngrok (expose local server to GitHub) |

---

## Event Display Formats

| Action | Format |
|---|---|
| **PUSH** | `"{author}" pushed to "{branch}" on {timestamp}` |
| **PULL REQUEST** | `"{author}" submitted a pull request from "{from_branch}" to "{to_branch}" on {timestamp}` |
| **MERGE** | `"{author}" merged branch "{from_branch}" to "{to_branch}" on {timestamp}` |

Timestamps are displayed as: `1st March 2026 - 11:48 AM UTC`

---

## MongoDB Schema

| Field | Type | Description |
|---|---|---|
| `_id` | ObjectID | MongoDB auto-generated ID |
| `request_id` | string | Commit SHA (push) or PR number (PR/merge) |
| `author` | string | GitHub username of the actor |
| `action` | string | One of: `PUSH`, `PULL_REQUEST`, `MERGE` |
| `from_branch` | string | Source branch |
| `to_branch` | string | Target branch |
| `timestamp` | string | UTC datetime in ISO-8601 format |

---

## Prerequisites

- **Python** 3.12+
- **Node.js** 18+ and **npm** 9+
- **Redis** 7+ (for Celery broker)
- **Docker** and **Docker Compose** (for containerised deployment)
- **ngrok** (authenticated) — [https://ngrok.com](https://ngrok.com)
- **MongoDB Atlas** cluster with a connection string (or use Docker MongoDB)
- **GitHub account** with a repository to monitor (`action-repo`)

---

## Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/NKVRK/webhook-repo.git
cd webhook-repo
```

### 2. Backend Setup

```bash
# Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Configure MongoDB

Set the `MONGO_URI` environment variable (or edit the default in `app/__init__.py`):

```bash
export MONGO_URI="mongodb+srv://<user>:<password>@<cluster>.mongodb.net/github_events_db?retryWrites=true&w=majority"
```

### 4. Start the Flask Server

```bash
python run.py
```

The server runs at `http://127.0.0.1:5000`.

### 5. Start Redis & Celery Worker

In separate terminals:

```bash
# Start Redis (if not running)
redis-server

# Start the Celery worker
celery -A celery_worker.celery worker --loglevel=info --concurrency=4
```

### 6. Frontend Setup

```bash
cd frontend

# Install Node.js dependencies
npm install

# Start the Vite dev server
npm run dev
```

The UI is available at `http://localhost:5173`.

> **Note:** The Vite dev server proxies `/webhook/*` requests to `http://127.0.0.1:5000` automatically.

### 7. Expose with ngrok

In a separate terminal:

```bash
ngrok http 5000
```

Copy the `https://...ngrok-free.dev` forwarding URL.

### 8. Configure GitHub Webhook

1. Go to your **action-repo** → **Settings** → **Webhooks** → **Add webhook**
2. Set the following:

| Setting | Value |
|---|---|
| Payload URL | `https://<your-ngrok-url>/webhook/receiver` |
| Content type | `application/json` |
| Events | Select **"Let me select individual events"** → check **Pushes** and **Pull requests** |
| Active | ✅ |

> **Note:** Merge events are automatically detected from Pull Request events (when a PR is closed with `merged: true`).

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/webhook/receiver` | Receives GitHub webhook payloads |
| `GET` | `/webhook/events/all` | Returns events from the last **15 seconds** (used for initial load + polling) |
| `GET` | `/webhook/events?after=<timestamp>` | Returns events after the given ISO-8601 timestamp (optional incremental query) |

---

## Docker Deployment

Run the entire stack (Flask + Celery + Redis + MongoDB + React frontend) with a single command:

```bash
docker-compose up --build
```

| Service | Container | Port |
|---|---|---|
| Flask Backend | `webhook-flask` | `5000` |
| Celery Worker | `webhook-celery-worker` | — |
| Redis | `webhook-redis` | `6379` |
| MongoDB | `webhook-mongodb` | `27017` |
| React Frontend | `webhook-frontend` | `80` |

To stop all services:

```bash
docker-compose down
```

To stop and remove data volumes:

```bash
docker-compose down -v
```

---

## Celery + Redis (Async Task Queue)

### Why Redis over RabbitMQ?

| Criteria | Redis | RabbitMQ |
|---|---|---|
| **Setup complexity** | Minimal — single binary, zero config | Requires Erlang runtime, management plugin |
| **Dual-purpose** | Acts as both broker AND result backend | Needs a separate result backend (e.g. Redis, DB) |
| **Resource footprint** | ~5 MB idle memory | ~100 MB+ with management plugin |
| **Docker image size** | ~30 MB (alpine) | ~200 MB+ |
| **Sufficient for this use case** | ✅ Webhook events are low-to-moderate volume | Overkill for this throughput |
| **Future utility** | Can also serve as cache layer | Single-purpose message broker |

**Conclusion:** Redis is the pragmatic choice — simpler deployment, lower resource usage, and perfectly adequate for the volume of GitHub webhook events this application handles.

### How it works

1. Flask receives a webhook → enqueues event into the **Tornado queue**
2. A Tornado worker dispatches a **Celery task** (`store_event`)
3. The Celery worker (connected to Redis) picks up the task and **stores it in MongoDB**
4. If Redis/Celery is unavailable, the app falls back to **direct MongoDB insertion**

### Running the Celery worker

```bash
celery -A celery_worker.celery worker --loglevel=info --concurrency=4
```

---

## Multithreading (Tornado Queue)

Concurrent webhook processing is implemented using **Tornado's `tornado.queues.Queue`** running in a background daemon thread.

Reference: [Tornado Queue Guide](https://www.tornadoweb.org/en/stable/guide/queues.html)

### How it works

- On app startup, a background thread starts a **Tornado IOLoop** with 3 worker coroutines.
- When a webhook arrives, the parsed event is enqueued via `enqueue()` (thread-safe).
- Workers consume events concurrently and dispatch Celery tasks.
- The Flask request handler returns **immediately** without blocking on DB writes.

```
Flask Thread                    Tornado Thread (daemon)
    │                               │
    │  enqueue(event)  ──────────►  Queue
    │  return 200                   │
    │                          Worker-0 ──► Celery task
    │                          Worker-1 ──► Celery task
    │                          Worker-2 ──► Celery task
```

### Key files

- `app/tornado_queue.py` — Queue, workers, `enqueue()`, `init_tornado_workers()`
- `app/tasks.py` — Celery task `store_event` dispatched by workers

---

## Logging

File-based logging with proper format is configured in `app/logging_config.py`.

### Format

```
timestamp | level    | module               | message
```

Example output:

```
2026-03-06 14:30:00 | INFO     | routes               | Received webhook: event_type=push
2026-03-06 14:30:00 | INFO     | tornado_queue         | Dispatched Celery task: action=PUSH, request_id=abc123
2026-03-06 14:30:01 | INFO     | tasks                 | Event stored via Celery: action=PUSH, request_id=abc123
```

### Configuration

| Setting | Value |
|---|---|
| Log file | `logs/app.log` |
| Rotation | 5 MB max, 5 backup files |
| Handlers | File (rotating) + Console |
| Level | `INFO` |

---

## Project Structure

```
webhook-repo/
├── run.py                  # Flask entry point
├── celery_worker.py        # Celery worker entry point
├── requirements.txt        # Python dependencies (pinned)
├── Dockerfile              # Flask backend Docker image
├── docker-compose.yml      # Full stack orchestration
├── .dockerignore           # Docker build exclusions
├── Celery and Message Queue Concepts.md  # Celery & MQ concepts guide
├── app/
│   ├── __init__.py         # App factory, config, DB indexes
│   ├── extensions.py       # Shared PyMongo instance
│   ├── logging_config.py   # File-based logging setup
│   ├── celery_app.py       # Celery + Redis configuration
│   ├── tasks.py            # Celery task definitions
│   ├── tornado_queue.py    # Tornado queue workers (multithreading)
│   └── webhook/
│       ├── __init__.py     # Blueprint package
│       └── routes.py       # Webhook receiver + polling API
├── frontend/
│   ├── Dockerfile          # React frontend Docker image
│   ├── nginx.conf          # Nginx config (SPA + API proxy)
│   ├── index.html          # HTML entry point
│   ├── vite.config.js      # Vite config (TailwindCSS + proxy)
│   ├── package.json        # Node.js dependencies
│   └── src/
│       ├── main.jsx        # React entry point
│       ├── App.jsx         # Root component with header
│       ├── index.css       # TailwindCSS import
│       ├── components/
│       │   ├── EventList.jsx   # Polling logic + event list
│       │   └── EventCard.jsx   # Single event display card
│       └── utils/
│           └── formatDate.js   # Timestamp formatting utility
├── logs/
│   └── app.log             # Application log file (auto-created)
└── screenshots/
    └── test_results.png    # Test results screenshot
```

---

## Test Results

All three event types — **Push**, **Pull Request**, and **Merge** — have been tested successfully on the `action-repo` and captured by the webhook receiver:

![Test Results — Push, Pull Request, and Merge events displayed in the UI](screenshots/test_results.png)

---

## Key Design Decisions

- **Duplicate Prevention (2 layers):**
  1. MongoDB unique compound index on `(request_id, action)`
  2. Backend `find_one` check before insert (direct fallback path)

- **15-Second Event Window:** The UI displays only events from the last 15 seconds. Each poll cycle replaces the displayed list entirely by querying `/webhook/events/all`, which applies a server-side `timedelta(seconds=15)` cutoff.

- **Async Processing Pipeline:** Webhook events flow through Tornado queue → Celery task → MongoDB, keeping the HTTP response fast and non-blocking.

- **Graceful Degradation:** If Redis/Celery or Tornado workers are unavailable, the app falls back to synchronous direct MongoDB insertion — the webhook never silently drops events.

- **Merge Detection:** GitHub sends merges as `pull_request` events with `action: "closed"` and `merged: true` — handled within the same webhook handler.

- **Error Handling:** All routes and background tasks are wrapped in `try–except` blocks. Malformed payloads return HTTP 400. Celery tasks auto-retry up to 3 times on failure. Errors are logged with full tracebacks.

- **Structured Logging:** Every module logs with a consistent format (`timestamp | level | module | message`) to both `logs/app.log` (rotating) and console.

- **Performance:** MongoDB indexes on `(request_id, action)` and `timestamp` ensure fast queries even as the events collection grows.

- **Containerisation:** Docker Compose orchestrates all 5 services (Flask, Celery worker, Redis, MongoDB, React/Nginx) with a single `docker-compose up` command.

---

## Codebase Walkthrough

See [Tour of codebase.md](Tour%20of%20codebase.md) for a detailed, file-by-file walkthrough of the entire project — covering the backend, frontend, and how they connect.

---

## Related Repository

- **[action-repo](https://github.com/NKVRK/action-repo)** — The monitored GitHub repository that triggers webhook events.