# Tour of Codebase

Hi, I'm Ramakrishna. Let me walk you through the codebase of my GitHub Webhook Receiver project — how the backend receives, queues, and stores events asynchronously, and how the frontend polls and displays them.

---

## Entry Point — [run.py](run.py)

This is where everything starts. It imports the `create_app` factory from the `app` package, creates the Flask application instance, and runs it on port `5000` with debug mode on. When the app starts, the factory automatically sets up logging, MongoDB, Celery, Tornado queue workers, and the webhook routes.

---

## App Factory — [app/\_\_init\_\_.py](app/__init__.py)

This is the application factory. I'm using the factory pattern so that the app is configurable and testable. Inside `create_app()`, I do the following in order:

1. **Configuration** — Set `MONGO_URI`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND` from environment variables (with sensible defaults for local dev).
2. **Logging** — Call `setup_logging(app)` to configure file-based and console logging with the format `timestamp | level | module | message`.
3. **MongoDB** — Initialize the PyMongo extension (wrapped in try/except so it logs a clear error if the connection fails).
4. **CORS** — Enable cross-origin requests so the React frontend can talk to Flask.
5. **Celery** — Bind the Celery instance to the Flask app context via `init_celery(app)`. If Redis isn't available, this logs a warning but doesn't crash — the app falls back to direct MongoDB writes.
6. **Tornado Workers** — Start 3 background queue worker coroutines via `init_tornado_workers()`. Again, wrapped in try/except for graceful degradation.
7. **Blueprint** — Register the webhook blueprint with all the routes.
8. **Indexes** — Call `_ensure_indexes()` to create MongoDB compound unique index on `(request_id, action)` and a descending index on `timestamp`.

---

## Shared Extensions — [app/extensions.py](app/extensions.py)

This file holds the shared `PyMongo` instance. I keep it separate from the app factory to avoid circular imports — the routes, tasks, and other modules can import `mongo` from here without importing the entire app.

---

## Logging — [app/logging\_config.py](app/logging_config.py)

Configures application-wide file-based logging. It creates a `logs/` directory at the project root (if it doesn't exist) and sets up two handlers:

- **RotatingFileHandler** — writes to `logs/app.log`, rotates at 5 MB with 5 backup files.
- **StreamHandler** — outputs to the console so you can see logs during development.

Both use the same format: `2026-03-06 14:30:00 | INFO     | routes               | Received webhook: event_type=push`. If a Flask app instance is passed in, its logger gets wired to the same handlers.

---

## Celery Configuration — [app/celery\_app.py](app/celery_app.py)

Creates the Celery instance and configures it to use **Redis** as both the message broker and result backend. The `init_celery(app)` function binds Celery to the Flask app by wrapping every task execution in the Flask application context — this lets tasks access Flask-managed resources like the `mongo` database connection.

I chose Redis over RabbitMQ because it's simpler to set up (one service instead of two), acts as both broker and backend, has a smaller Docker footprint, and is perfectly adequate for the moderate throughput of webhook events.

---

## Celery Tasks — [app/tasks.py](app/tasks.py)

Defines the `store_event` task — the Celery task that actually writes parsed events to MongoDB. Key features:

- **Idempotent** — If a duplicate event (same `request_id` + `action`) already exists, the insert is silently skipped thanks to the unique compound index catching a `DuplicateKeyError`.
- **Auto-retry** — On unexpected database errors, the task retries up to 3 times with a 5-second delay between attempts (`bind=True, max_retries=3, default_retry_delay=5`).
- **Deferred import** — The `mongo` instance is imported inside the task function to avoid circular imports.

---

## Tornado Queue Workers — [app/tornado\_queue.py](app/tornado_queue.py)

This is the multithreading layer, implemented using Tornado's `tornado.queues.Queue` (following the [Tornado Queue Guide](https://www.tornadoweb.org/en/stable/guide/queues.html)).

On app startup, `init_tornado_workers()` spawns a background daemon thread that runs a Tornado IOLoop with 3 worker coroutines. When a webhook arrives, the Flask route handler calls `enqueue(event)` — a thread-safe function that uses `IOLoop.add_callback` to put the event into the shared queue from the Flask thread. Each Tornado worker picks up events and dispatches them as Celery tasks via `store_event.delay()`.

This keeps the Flask request-response cycle fast — the HTTP 200 is returned immediately, and the actual database write happens asynchronously in the background.

---

## Celery Worker Entry Point — [celery\_worker.py](celery_worker.py)

This is the entry point for running the Celery worker process. It creates the Flask app (so extensions and config are initialized) and exposes the `celery` instance for the Celery CLI:

```bash
celery -A celery_worker.celery worker --loglevel=info --concurrency=4
```

---

## Webhook Routes — [app/webhook/routes.py](app/webhook/routes.py)

This is the core of the backend. All three endpoints are wrapped in outer try/except blocks that catch unexpected errors, log full tracebacks, and return a 500 instead of crashing.

### `POST /webhook/receiver`

Receives incoming webhook payloads from GitHub. First, it validates the JSON body — if it's missing, it returns a `400`. Then it checks the `X-GitHub-Event` header:

- **Ping** — responds with `"pong"` (GitHub sends this when you first set up the webhook).
- **Push** — extracts commit SHA, author, branch, and timestamp. Branch deletion events (no `head_commit`) are silently ignored.
- **Pull Request** — checks the `action` field. If the PR was `closed` with `merged: true`, it's a **MERGE** event. If `opened` or `reopened`, it's a **PULL_REQUEST**. Other sub-actions (`labeled`, `edited`, etc.) are skipped via a `ValueError`.

After parsing, the event is enqueued into the Tornado queue for async processing. If the Tornado queue isn't available (e.g., startup timing), it falls back to `_store_event_direct()` — a synchronous path that does a `find_one` duplicate check then `insert_one`.

### `GET /webhook/events/all`

Returns events from the **last 15 seconds**, sorted newest-first. This endpoint is used by the frontend for both the initial page load and every subsequent poll cycle. A server-side `timedelta(seconds=15)` cutoff is applied, so the UI always shows only recent activity.

### `GET /webhook/events?after=<timestamp>`

Returns events whose timestamp is strictly after the `after` query parameter. This is an optional incremental query endpoint — the frontend currently uses `/events/all` for polling, but this endpoint is available for alternative polling strategies.

### Helper functions

- `_parse_timestamp()` — normalizes GitHub's ISO timestamps (which can have timezone offsets) into a consistent UTC format: `YYYY-MM-DDTHH:MM:SSZ`. Wrapped in try/except with logging.
- `_serialize_event()` — converts a MongoDB document into a JSON-friendly dict by turning the `_id` ObjectId into a string.
- `_store_event_direct()` — fallback synchronous storage path when the async pipeline is unavailable.

---

## Docker — [Dockerfile](Dockerfile), [docker-compose.yml](docker-compose.yml)

The project is fully containerised. The backend `Dockerfile` uses `python:3.12-slim`, installs dependencies, and runs `python run.py`. The frontend has its own multi-stage `Dockerfile` — stage 1 builds the React app with Node, stage 2 serves the built files from nginx.

`docker-compose.yml` orchestrates 5 services:

| Service | Image | Port |
|---|---|---|
| Flask Backend | Built from `./Dockerfile` | 5000 |
| Celery Worker | Same image, different command | — |
| Redis | `redis:7-alpine` | 6379 |
| MongoDB | `mongo:7` | 27017 |
| React Frontend | Built from `./frontend/Dockerfile` | 80 |

The nginx config (`frontend/nginx.conf`) proxies `/webhook` requests to the Flask container and serves the SPA with a `try_files` fallback for client-side routing.

---

## Vite Config — [frontend/vite.config.js](frontend/vite.config.js)

On the frontend side, I'm using Vite with React and TailwindCSS. The important thing here is the proxy configuration — any request the frontend makes to `/webhook` gets proxied to `http://127.0.0.1:5000`. This means during development I don't have to worry about CORS between the Vite dev server (port 5173) and Flask (port 5000).

---

## React Entry — [frontend/src/main.jsx](frontend/src/main.jsx)

Standard React entry point. It renders the `App` component into the root DOM element.

---

## App Component — [frontend/src/App.jsx](frontend/src/App.jsx)

The top-level component. It renders a header with a GitHub SVG icon and the title "GitHub Webhook Events", then renders the `EventList` component below it. Simple layout, nothing else going on here.

---

## EventList Component — [frontend/src/components/EventList.jsx](frontend/src/components/EventList.jsx)

This is where the polling logic lives. On mount, it calls `/webhook/events/all` to fetch events from the last 15 seconds. Then it sets up a `setInterval` that fires every 15 seconds, calling the same endpoint again — each poll **replaces** the displayed events entirely with the latest 15-second window from the server.

This is simpler than the old incremental approach — no timestamp tracking or client-side deduplication needed, since the server handles the time window and the UI just shows whatever comes back.

There's also:

- A **countdown timer** that shows how many seconds until the next poll.
- A **loading spinner** on first load.
- An **error banner** (red) if a fetch fails, so the user knows something went wrong.
- An **empty state** message if no events have been received yet.

Each event gets rendered as an `EventCard`.

---

## EventCard Component — [frontend/src/components/EventCard.jsx](frontend/src/components/EventCard.jsx)

Each event is displayed as a color-coded card:

- **PUSH** — green badge and border
- **PULL_REQUEST** — blue badge and border
- **MERGE** — purple badge and border

The `buildMessage()` function constructs the display text based on the event type, following the exact format specified in the requirements. For example, a push event shows something like: *`"testuser" pushed to "main" on 1st March 2026 - 2:30 PM UTC`*. Each card also has a small icon (arrow-up for push, arrows for PR, arrow-right for merge) next to the action badge.

---

## Date Formatting — [frontend/src/utils/formatDate.js](frontend/src/utils/formatDate.js)

This utility converts ISO timestamps into the human-readable format the requirements asked for: `1st March 2026 - 2:30 PM UTC`. The `getOrdinalSuffix()` function handles the day suffix correctly — including the special cases for 11th, 12th, and 13th which don't follow the usual st/nd/rd pattern.

---

## Styles — [frontend/src/index.css](frontend/src/index.css)

Just a single line: `@import "tailwindcss";`. I'm using TailwindCSS v4, which handles everything through this import. All the styling is done with utility classes directly in the JSX.

---

## Dependencies — [requirements.txt](requirements.txt)

All Python dependencies are pinned to exact versions for reproducibility:

- **Flask** — web framework
- **Flask-PyMongo** — MongoDB integration for Flask
- **Flask-Cors** — cross-origin request handling
- **pymongo** — MongoDB driver
- **dnspython** — required for MongoDB Atlas SRV connection strings
- **certifi** — SSL certificates for secure Atlas connections
- **celery[redis]** — distributed task queue with Redis transport
- **redis** — Python Redis client
- **tornado** — async framework used for multithreaded queue workers

---

## Concepts Guide — [Celery and Message Queue Concepts.md](Celery%20and%20Message%20Queue%20Concepts.md)

A comprehensive reference document covering message queue fundamentals, Celery architecture, Redis vs RabbitMQ comparison, task lifecycle, retry strategies, concurrency models, and how all of these are applied in this project.

---

That covers the entire codebase. The backend receives webhooks, enqueues them into a Tornado queue, dispatches Celery tasks via Redis, and stores events in MongoDB — all asynchronously. If the async pipeline isn't available, it falls back to direct synchronous storage. The frontend polls the backend every 15 seconds and replaces the displayed events with the latest 15-second window, rendering them as color-coded cards. The whole stack can be run with a single `docker-compose up` command.
