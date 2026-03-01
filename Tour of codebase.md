# Tour of Codebase

Hi, I'm Ramakrishna. Let me walk you through the codebase of my GitHub Webhook Receiver project — how the backend receives and stores events, and how the frontend polls and displays them.

---

## Entry Point — [run.py](run.py)

This is where everything starts. It imports the `create_app` factory from the `app` package, creates the Flask application instance, and runs it on port `5000` with debug mode on. Pretty standard Flask entry point, nothing fancy here.

---

## App Factory — [app/\_\_init\_\_.py](app/__init__.py)

This is the application factory. I'm using the factory pattern so that the app is configurable and testable. Inside `create_app()`, I:

- Set the `MONGO_URI` from an environment variable, with a fallback to my MongoDB Atlas connection string.
- Initialize the PyMongo extension so I can talk to the database.
- Enable CORS so the React frontend can make requests to the Flask backend without running into cross-origin issues.
- Register the webhook blueprint, which holds all the route logic.
- Call `_ensure_indexes()` at startup — this creates a compound unique index on `(request_id, action)` to prevent duplicate events, and a descending index on `timestamp` so queries sorting by time are fast.

---

## Shared Extensions — [app/extensions.py](app/extensions.py)

This file just holds the shared `PyMongo` instance. I keep it separate from the app factory to avoid circular imports — the routes module can import `mongo` from here without importing the entire app.

---

## Webhook Routes — [app/webhook/routes.py](app/webhook/routes.py)

This is the core of the backend, so let me break it down.

### `POST /webhook/receiver`

This endpoint receives incoming webhook payloads from GitHub. First, it checks if the request has valid JSON — if not, it returns a `400`. Then it looks at the `X-GitHub-Event` header to figure out what kind of event came in. If it's a `ping` (GitHub sends this when you first set up the webhook), it just responds with `"pong"`.

For actual events, it delegates to a helper called `_parse_event()`, which extracts the relevant fields based on the event type:

- **Push events**: I pull out the latest commit SHA (shortened to 7 characters), the author name, the branch (stripped from `refs/heads/`), and the timestamp.
- **Pull Request events**: I check the `action` field. If the PR was `closed` and `merged` is `true`, I treat it as a **MERGE** event. If it was `opened` or `reopened`, it's a **PULL_REQUEST** event. Any other PR action (like `labeled` or `edited`) gets ignored — I raise a `ValueError` for those, which the caller catches and returns a `200` with `"ignored"`.

After parsing, I check for duplicates using `find_one` on the `request_id` and `action` combo. If the event already exists, I skip the insert. Otherwise, I insert it into the `events` collection.

The whole parsing is wrapped in a try/except — `ValueError` means the event was intentionally skipped, and `KeyError` or `TypeError` means the payload was malformed, which returns a `400`.

### `GET /webhook/events`

This is the polling endpoint. The frontend calls this every 15 seconds with an `after` query parameter (a timestamp). The backend returns only events whose `timestamp` is strictly greater than `after`, sorted newest-first. This way the frontend never re-fetches events it already has.

### `GET /webhook/events/all`

Returns every event in the collection, sorted newest-first. The frontend calls this once on initial load to get the full history.

### Helper functions

- `_parse_timestamp()` normalizes GitHub's ISO timestamps (which can have timezone offsets) into a consistent UTC format: `YYYY-MM-DDTHH:MM:SSZ`.
- `_serialize_event()` converts a MongoDB document into a JSON-friendly dict. It makes a shallow copy first so it doesn't mutate the original document, then converts the `_id` ObjectId to a string.

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

This is where the polling logic lives. On mount, it calls `/webhook/events/all` to fetch the full event history. Then it sets up a `setInterval` that fires every 15 seconds, calling `/webhook/events?after=<latest_timestamp>` to get only new events since the last fetch.

I use `useCallback` for the merge logic — when new events come in, they get prepended to the existing list (newest first). The `latestTs` ref tracks the most recent timestamp so the next poll knows where to start.

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

The `buildMessage()` function constructs the display text based on the event type, following the exact format specified in the requirements. For example, a push event shows something like: *`"testuser" pushed to "main" on 1st March 2026 - 2:30 PM UTC`*. Each card also has a small icon (arrow-up for push, git-branch for PR, git-merge for merge) next to the action badge.

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

---

That covers the entire codebase. The backend receives webhooks, parses them, deduplicates, and stores them in MongoDB. The frontend polls the backend every 15 seconds and renders new events as color-coded cards — no duplicates, no full refreshes, just incremental updates.
