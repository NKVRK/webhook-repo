# Celery & Message Queue Concepts

A comprehensive guide to the message queue architecture used in this project.

---

## Table of Contents

1. [What is a Message Queue?](#what-is-a-message-queue)
2. [Why Use a Message Queue?](#why-use-a-message-queue)
3. [What is Celery?](#what-is-celery)
4. [Celery Architecture](#celery-architecture)
5. [Broker: Redis vs RabbitMQ](#broker-redis-vs-rabbitmq)
6. [How Celery Works in This Project](#how-celery-works-in-this-project)
7. [Key Celery Concepts](#key-celery-concepts)
8. [Task Lifecycle](#task-lifecycle)
9. [Error Handling & Retries](#error-handling--retries)
10. [Concurrency Models](#concurrency-models)
11. [When to Use Celery](#when-to-use-celery)

---

## What is a Message Queue?

A **message queue** is a communication mechanism that allows different parts of an application (or different applications entirely) to exchange information asynchronously by sending messages through a shared queue.

```
Producer  ──►  [ Queue ]  ──►  Consumer
 (sends)       (stores)       (processes)
```

### Core Principles

- **Decoupling** — The producer doesn't need to know who consumes the message, or when. It just puts the message on the queue and moves on.
- **Asynchronous processing** — The producer doesn't wait for the consumer to finish. It sends the message and immediately continues its own work.
- **Buffering** — The queue holds messages until consumers are ready to process them, smoothing out spikes in workload.
- **Guaranteed delivery** — Messages persist in the queue until explicitly acknowledged by a consumer, ensuring nothing is lost even if a consumer crashes.

### Real-World Analogy

Think of a restaurant:
- **Customer** (producer) places an order (message)
- **Order queue** (message queue) holds the ticket on the kitchen rail
- **Chef** (consumer) picks up orders and prepares them
- The customer doesn't stand in the kitchen waiting — they sit down and continue their meal

---

## Why Use a Message Queue?

| Problem | How a Queue Solves It |
|---|---|
| **Slow API responses** | Offload heavy work to background workers; respond to the client immediately |
| **Coupled services** | Producer and consumer evolve independently; neither needs to know about the other |
| **Traffic spikes** | Queue absorbs bursts; workers process at their own pace |
| **Unreliable downstream** | If a worker fails, the message stays in the queue and is retried |
| **Scaling** | Add more workers to increase throughput without changing the producer |

### Without a Queue (Synchronous)

```
Client  ──►  Flask  ──►  MongoDB  ──►  Flask  ──►  Client
              │                          │
              └── waits for DB write ────┘
              (slow: 50-200ms blocking)
```

### With a Queue (Asynchronous)

```
Client  ──►  Flask  ──►  Queue  ──►  Client (200 OK immediately)
                           │
                      Background Worker
                           │
                        MongoDB (non-blocking)
```

---

## What is Celery?

**Celery** is a distributed task queue for Python. It lets you define **tasks** (Python functions) that run asynchronously in separate **worker** processes, triggered by messages sent through a **broker**.

### Key Properties

- **Distributed** — Workers can run on multiple machines
- **Language** — Pure Python (tasks are just decorated functions)
- **Broker-agnostic** — Supports Redis, RabbitMQ, Amazon SQS, and more
- **Battle-tested** — Used by Instagram, Mozilla, AdRoll, and thousands of production systems

### Minimal Example

```python
from celery import Celery

# Create a Celery app connected to a Redis broker
app = Celery('my_app', broker='redis://localhost:6379/0')

# Define a task
@app.task
def add(x, y):
    return x + y

# Call the task asynchronously (returns immediately)
result = add.delay(4, 6)

# Optionally wait for the result
print(result.get(timeout=10))  # → 10
```

---

## Celery Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│  Application│────►│   Broker     │────►│   Worker(s)  │────►│   Result     │
│  (Producer) │     │  (Redis/     │     │  (Consumer)  │     │   Backend    │
│             │     │   RabbitMQ)  │     │              │     │  (Redis/DB)  │
└─────────────┘     └──────────────┘     └─────────────┘     └──────────────┘
      │                   │                    │                     │
  Sends task          Stores task          Executes task        Stores result
  message             message in           function code        (optional)
  (.delay())          a queue              with args
```

### Components Explained

| Component | Role | Example |
|---|---|---|
| **Application** | Defines and sends tasks | Flask web server |
| **Broker** | Message transport — receives, stores, and delivers task messages | Redis, RabbitMQ |
| **Worker** | Separate process that consumes messages and runs task code | `celery -A app worker` |
| **Result Backend** | Stores task return values and state (optional — not always needed) | Redis, PostgreSQL, MongoDB |

---

## Broker: Redis vs RabbitMQ

### Redis

**Redis** (Remote Dictionary Server) is an in-memory key-value store that Celery can use as a message broker.

**Pros:**
- Extremely fast (in-memory, single-threaded event loop)
- Simple to install and operate (`redis-server` — done)
- Serves as **both** broker and result backend — no extra service
- Lightweight Docker image (~30 MB)
- Useful beyond queueing: caching, sessions, pub/sub, rate limiting

**Cons:**
- Messages are in-memory — risk of loss if Redis crashes without persistence
- No built-in message routing, priorities, or dead-letter exchanges
- Not designed specifically for messaging (it's a general-purpose store)

### RabbitMQ

**RabbitMQ** is a dedicated message broker implementing the AMQP protocol.

**Pros:**
- Purpose-built for messaging — feature-rich (routing, priorities, dead-letter queues, acknowledgments)
- Messages persist to disk by default — better durability guarantees
- Management UI for monitoring queues, consumers, and throughput
- Supports complex routing patterns (topic exchanges, header routing)

**Cons:**
- Heavier setup — requires Erlang runtime
- More operational complexity (cluster management, configuration)
- Larger Docker image (~200 MB+)
- Needs a separate result backend

### Why We Chose Redis

For this webhook project:
- **Volume is moderate** — GitHub webhooks arrive at human pace, not millions per second
- **Simplicity matters** — one service (Redis) instead of two (RabbitMQ + result backend)
- **Docker footprint** — smaller image, faster CI/CD builds
- **Future utility** — Redis can also be used for caching API responses or rate-limiting webhooks

---

## How Celery Works in This Project

### Flow

```
1. GitHub sends webhook POST to Flask
           │
2. Flask parses the event payload
           │
3. Event data is enqueued into Tornado Queue (concurrent, non-blocking)
           │
4. Tornado worker dispatches: store_event.delay(event_data)
           │
5. Celery serialises the task call to JSON and pushes it to Redis
           │
6. A Celery worker process picks up the message from Redis
           │
7. The worker executes store_event() → inserts into MongoDB
           │
8. Result status ("stored" / "duplicate") is written back to Redis
```

### Project Files

| File | Purpose |
|---|---|
| `app/celery_app.py` | Creates the Celery instance, configures Redis URLs, binds to Flask app context |
| `app/tasks.py` | Defines `store_event` — the Celery task that writes events to MongoDB |
| `celery_worker.py` | Entry point for `celery -A celery_worker.celery worker` CLI command |
| `app/tornado_queue.py` | Tornado queue workers that dispatch Celery tasks concurrently |

### Running the Worker

```bash
# Start a Celery worker with 4 concurrent processes
celery -A celery_worker.celery worker --loglevel=info --concurrency=4
```

---

## Key Celery Concepts

### 1. Task

A **task** is a Python function decorated with `@app.task`. It's the unit of work that Celery executes.

```python
@celery.task(bind=True, max_retries=3)
def store_event(self, event_data):
    """Store a webhook event in MongoDB."""
    mongo.db.events.insert_one(event_data)
```

- `bind=True` — gives the task access to `self` (the task instance), needed for retries
- `max_retries=3` — automatically retry up to 3 times on failure

### 2. Calling Tasks

| Method | Behaviour |
|---|---|
| `task.delay(arg1, arg2)` | Shortcut for `.apply_async()` — sends task to the broker immediately |
| `task.apply_async(args=[...], countdown=60)` | Full-featured call with scheduling options |
| `task(arg1, arg2)` | Runs the task **synchronously** (no broker involved — rarely used) |

```python
# Async (non-blocking) — returns an AsyncResult immediately
result = store_event.delay(event_data)

# Async with options
result = store_event.apply_async(
    args=[event_data],
    countdown=10,        # delay execution by 10 seconds
    expires=300,         # discard if not processed within 5 minutes
)

# Get the result (blocks until done)
print(result.get(timeout=30))  # → {"status": "stored", "request_id": "abc123"}
```

### 3. AsyncResult

When you call `.delay()`, you get back an `AsyncResult` object:

```python
result = store_event.delay(event_data)

result.id          # Unique task ID (UUID)
result.status      # 'PENDING', 'STARTED', 'SUCCESS', 'FAILURE', 'RETRY'
result.ready()     # True if task has finished
result.get()       # Block and return the result
result.traceback   # Traceback string if task failed
```

### 4. Worker

A **worker** is a separate process (or processes) that:
1. Connects to the broker
2. Listens for messages
3. Deserialises the message back into a function call
4. Executes the function
5. Writes the result to the result backend

```bash
celery -A celery_worker.celery worker --loglevel=info --concurrency=4
#                                                       └── 4 child processes
```

### 5. Serialization

Celery serialises task arguments to send them over the wire. Supported formats:
- **JSON** (default, recommended) — human-readable, safe
- **pickle** — Python-specific, supports complex objects, but has security risks
- **msgpack** — compact binary format

```python
celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
)
```

---

## Task Lifecycle

```
     .delay()           Broker              Worker
        │                 │                   │
        ├──── PENDING ────►                   │
        │                 ├──── RECEIVED ────►│
        │                 │                   ├── STARTED
        │                 │                   │     │
        │                 │                   │     ├── (executing code...)
        │                 │                   │     │
        │                 │                   ├── SUCCESS ──► Result Backend
        │                 │                   │     OR
        │                 │                   ├── FAILURE ──► (retry or give up)
        │                 │                   │     OR
        │                 │                   ├── RETRY  ──► back to Broker
```

### States

| State | Meaning |
|---|---|
| **PENDING** | Task has been sent but not yet received by a worker |
| **RECEIVED** | Worker has received the task message |
| **STARTED** | Worker has begun executing the task |
| **SUCCESS** | Task completed without error |
| **FAILURE** | Task raised an exception |
| **RETRY** | Task failed and has been re-queued for another attempt |
| **REVOKED** | Task was cancelled before execution |

---

## Error Handling & Retries

### Automatic Retries

```python
@celery.task(bind=True, max_retries=3, default_retry_delay=5)
def store_event(self, event_data):
    try:
        mongo.db.events.insert_one(event_data)
    except Exception as exc:
        # Re-queue the task for retry (after 5s delay)
        raise self.retry(exc=exc)
```

### Retry with Exponential Backoff

```python
@celery.task(bind=True, max_retries=5)
def resilient_task(self, data):
    try:
        do_work(data)
    except TransientError as exc:
        raise self.retry(
            exc=exc,
            countdown=2 ** self.request.retries,  # 1s, 2s, 4s, 8s, 16s
        )
```

### What Happens After Max Retries?

If all retries are exhausted, the task enters the **FAILURE** state. You can handle this with:

```python
@celery.task(bind=True, max_retries=3)
def my_task(self, data):
    try:
        do_work(data)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            # All retries exhausted — log and give up
            logger.critical("Task permanently failed: %s", exc)
            return {"status": "failed"}
        raise self.retry(exc=exc)
```

---

## Concurrency Models

Celery workers support multiple concurrency models:

| Model | Flag | Best For |
|---|---|---|
| **Prefork** (default) | `--pool=prefork` | CPU-bound tasks (uses multiprocessing) |
| **Threads** | `--pool=threads` | I/O-bound tasks (HTTP calls, DB queries) |
| **Eventlet** | `--pool=eventlet` | High-concurrency I/O (green threads) |
| **Gevent** | `--pool=gevent` | Similar to eventlet (uses gevent library) |
| **Solo** | `--pool=solo` | Debugging (processes one task at a time) |

### For This Project

We use **prefork** (default) with `--concurrency=4` — each worker spawns 4 child processes. Since our task (`store_event`) does a MongoDB insert (I/O-bound), we could also use `--pool=threads` for lighter overhead:

```bash
# Option A: Process-based (default, robust)
celery -A celery_worker.celery worker --concurrency=4

# Option B: Thread-based (lighter for I/O tasks)
celery -A celery_worker.celery worker --pool=threads --concurrency=8
```

---

## When to Use Celery

### Good Use Cases

- **Webhook processing** — respond immediately, process in background (this project!)
- **Email sending** — don't block the request while SMTP connects
- **Image/video processing** — CPU-heavy work in background workers
- **Report generation** — long-running data aggregation
- **Scheduled jobs** — Celery Beat for periodic tasks (e.g., cleanup old events)
- **Third-party API calls** — rate-limited external services

### When NOT to Use Celery

- **Simple synchronous operations** — if the task takes <50ms, just do it inline
- **Real-time streaming** — use WebSockets or Server-Sent Events instead
- **Data pipelines at scale** — consider Apache Kafka, Apache Spark, or Airflow
- **Simple cron jobs** — a basic `cron` entry or `schedule` library may suffice

---

## Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                     This Project's Stack                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  GitHub Webhook ──► Flask ──► Tornado Queue ──► Celery Task     │
│                      │              │               │           │
│                      │         (concurrent       (async         │
│                      │          workers)       processing)      │
│                      │                              │           │
│                      │                         ┌────▼────┐      │
│                      ▼                         │  Redis  │      │
│                 Return 200                     │ (broker) │     │
│                 immediately                    └────┬────┘      │
│                                                    │            │
│                                               ┌────▼────┐      │
│                                               │ MongoDB │      │
│                                               │ (store) │      │
│                                               └─────────┘      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

Celery with Redis provides a robust, scalable, and maintainable way to handle webhook events asynchronously — keeping the API fast, the architecture decoupled, and the system resilient to failures.
