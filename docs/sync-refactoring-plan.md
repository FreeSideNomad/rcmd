# Sync Runtime Refactoring Plan

## Executive Summary

The current sync wrapper approach (wrapping async code with `SyncRuntime.run()`) has fundamental architectural problems causing connection pool exhaustion, threading complexity, and operational fragility. This document outlines a plan to implement **native synchronous components** using psycopg3's synchronous `ConnectionPool` class, replacing the wrapper pattern entirely.

## Problem Statement

### Current Issues (Evidence from Recent Commits)

| Commit | Issue | Root Cause |
|--------|-------|------------|
| `6ee00af` | Throttle sync worker concurrency | Pool exhaustion |
| `7d14c0d` | Auto-cap pool based on server limits | Connection starvation |
| `7379b37` | Cap sync worker concurrency based on pool | Threading/pool mismatch |
| `2080369` | Right-size worker DB pool | Async assumptions invalid for sync |
| `eb4a5fa` | Improve sync worker diagnostics | Silent failures |

### Fundamental Flaw

The async code assumes cooperative multitasking where tasks yield connections during I/O waits. Sync wrappers block threads, holding connections for entire operation durations. This mismatch causes:

1. **Connection exhaustion**: N concurrent sync calls = N connections held
2. **Thread proliferation**: Multiple thread pools + background event loop
3. **Complex shutdown**: Coordinating threads, executors, and event loops
4. **Silent failures**: Exceptions lost in thread boundaries

---

## Scope Analysis

### Components Requiring Native Sync Implementation

Based on comprehensive codebase analysis, the following components need sync variants:

#### Tier 1: Core Data Access (Must Change)

| Component | File | Async Patterns | Sync Replacement |
|-----------|------|----------------|------------------|
| **PgmqClient** | `pgmq/client.py` | `AsyncConnectionPool`, `async with conn.cursor()` | `ConnectionPool`, sync cursor |
| **PostgresCommandRepository** | `repositories/command.py` | 20+ async methods, stored procedures | Sync methods with `ConnectionPool` |
| **PostgresAuditLogger** | `repositories/audit.py` | 3 async methods | Sync equivalents |
| **PostgresBatchRepository** | `repositories/batch.py` | 10+ async methods, stored procedures | Sync equivalents |
| **PostgresProcessRepository** | `process/repository.py` | 13 async methods | Sync equivalents |

#### Tier 2: Orchestration Layer (Must Change)

| Component | File | Async Patterns | Sync Replacement |
|-----------|------|----------------|------------------|
| **CommandBus** | `bus.py` | 7 async methods, transactions | `SyncCommandBus` (native) |
| **Worker** | `worker.py` | `asyncio.Semaphore`, `asyncio.Task`, `asyncio.Event`, notification listener | `SyncWorker` with `ThreadPoolExecutor` |
| **ProcessReplyRouter** | `process/router.py` | Same as Worker | `SyncProcessReplyRouter` with threads |
| **BaseProcessManager** | `process/base.py` | 11 async methods | `SyncBaseProcessManager` |

#### Tier 3: Support Layer (Minor Changes)

| Component | File | Change Required |
|-----------|------|-----------------|
| **HandlerRegistry** | `handler.py` | Support sync handlers alongside async |
| **TroubleshootingQueue** | `ops/troubleshooting.py` | Native sync variant |
| **setup.py** | `setup.py` | Sync setup functions |

#### Unchanged Components

- **Models** (`models.py`) - Pure dataclasses, no I/O
- **Policies** (`policies.py`) - Pure logic
- **Exceptions** (`exceptions.py`) - No I/O
- **Handler decorators** - Metadata only

### Dependency Graph

```
┌─────────────────────────────────────────────────────────────────┐
│                        User Application                         │
│    (SyncCommandBus, SyncWorker, SyncProcessReplyRouter)         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
┌──────────────────┐ ┌──────────┐ ┌────────────────────┐
│  SyncCommandBus  │ │SyncWorker│ │SyncProcessReplyRouter│
└────────┬─────────┘ └────┬─────┘ └──────────┬─────────┘
         │                │                   │
         └────────────────┼───────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Repository Layer                           │
│  (SyncPgmqClient, SyncCommandRepository, SyncAuditLogger,       │
│   SyncBatchRepository, SyncProcessRepository)                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   psycopg3 ConnectionPool                       │
│                   (Synchronous, Thread-Safe)                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Design: Native Sync Implementation

### Connection Pool Configuration

Use psycopg3's synchronous `ConnectionPool` (thread-safe by design):

```python
from psycopg_pool import ConnectionPool

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=4,                    # Minimum connections maintained
    max_size=16,                   # Maximum under load
    timeout=30.0,                  # Wait time for getconn()
    max_lifetime=3600.0,           # 1 hour max connection age
    max_idle=600.0,                # 10 min idle before close
    num_workers=3,                 # Background maintenance threads
    check=ConnectionPool.check_connection,  # Validate on checkout
    reconnect_timeout=300.0,       # 5 min reconnection attempts
    reconnect_failed=on_reconnect_failed,   # Callback on failure
)
```

**Key Parameters:**

| Parameter | Purpose | Recommended Value |
|-----------|---------|-------------------|
| `min_size` | Base connections always available | `max(4, worker_concurrency)` |
| `max_size` | Ceiling under load | `min_size * 2` or server limit |
| `timeout` | Fail-fast on exhaustion | 30 seconds |
| `max_lifetime` | Prevent stale connections | 1 hour |
| `check` | Validate before use | `check_connection` |
| `reconnect_timeout` | Recovery window | 5 minutes |

### Sync Worker Architecture

```python
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from psycopg_pool import ConnectionPool
from queue import Queue, Empty
from typing import Callable

class SyncWorker:
    """Native synchronous worker using thread pool for concurrency."""

    def __init__(
        self,
        pool: ConnectionPool,
        domain: str,
        registry: HandlerRegistry,
        *,
        concurrency: int = 4,
        poll_interval: float = 1.0,
        visibility_timeout: int = 30,
        statement_timeout: int = 25000,  # ms, < visibility_timeout
    ):
        self._pool = pool
        self._domain = domain
        self._registry = registry
        self._concurrency = concurrency
        self._poll_interval = poll_interval
        self._visibility_timeout = visibility_timeout
        self._statement_timeout = statement_timeout

        self._executor: ThreadPoolExecutor | None = None
        self._stop_event = threading.Event()
        self._in_flight: dict[str, Future] = {}
        self._in_flight_lock = threading.Lock()
        self._health_status = HealthStatus()

    def run(self) -> None:
        """Main worker loop - blocks until stop() called."""
        self._executor = ThreadPoolExecutor(
            max_workers=self._concurrency,
            thread_name_prefix=f"worker-{self._domain}",
        )

        try:
            while not self._stop_event.is_set():
                self._poll_and_dispatch()
        finally:
            self._drain_in_flight()
            self._executor.shutdown(wait=True)

    def _poll_and_dispatch(self) -> None:
        """Read messages and dispatch to thread pool."""
        available_slots = self._concurrency - len(self._in_flight)
        if available_slots <= 0:
            self._wait_for_slot()
            return

        messages = self._read_batch(limit=available_slots)
        for msg in messages:
            future = self._executor.submit(self._process_message, msg)
            with self._in_flight_lock:
                self._in_flight[msg.msg_id] = future
            future.add_done_callback(
                lambda f, mid=msg.msg_id: self._on_complete(mid, f)
            )

    def _process_message(self, msg: Message) -> None:
        """Process single message with dedicated connection."""
        with self._pool.connection() as conn:
            # Set statement timeout for this connection
            conn.execute(
                f"SET statement_timeout = {self._statement_timeout}"
            )
            try:
                with conn.transaction():
                    # ... handle message ...
                    pass
            except Exception as e:
                self._health_status.record_failure(e)
                raise
```

### Sync Handler Support

Handlers can be either sync or async (for migration compatibility):

```python
from typing import Callable, Any, Union, Awaitable
import asyncio
import inspect

HandlerFn = Callable[[Command, HandlerContext], Any]
AsyncHandlerFn = Callable[[Command, HandlerContext], Awaitable[Any]]

class SyncHandlerRegistry:
    """Registry supporting both sync and async handlers."""

    def dispatch(self, command: Command, context: HandlerContext) -> Any:
        handler = self._handlers.get(command.command_type)
        if handler is None:
            raise UnknownCommandTypeError(command.command_type)

        result = handler(command, context)

        # Support async handlers during migration
        if inspect.iscoroutine(result):
            return asyncio.run(result)
        return result
```

---

## Runaway Process Handling

### Problem: Long-Running Operations

A handler that exceeds the visibility timeout causes:
1. Message becomes visible again (duplicate processing)
2. Connection held indefinitely
3. Thread blocked, reducing effective concurrency
4. Potential cascade failure

### Solution: Multi-Layer Timeout Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                    Timeout Hierarchy                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Layer 1: PostgreSQL statement_timeout (server-side)            │
│  ├── Kills query on server after N ms                           │
│  ├── Frees server resources immediately                         │
│  └── Set per-connection: SET statement_timeout = 25000          │
│                                                                 │
│  Layer 2: Connection pool timeout (client-side)                 │
│  ├── ConnectionPool(timeout=30) for getconn()                   │
│  └── Prevents indefinite wait for connections                   │
│                                                                 │
│  Layer 3: Visibility timeout (message-level)                    │
│  ├── PGMQ visibility_timeout = 30 seconds                       │
│  ├── Message reappears if not deleted                           │
│  └── statement_timeout < visibility_timeout (always)            │
│                                                                 │
│  Layer 4: Thread timeout (application-level)                    │
│  ├── Future.result(timeout=visibility_timeout + buffer)         │
│  ├── Worker can abandon stuck thread                            │
│  └── Thread may leak but worker continues                       │
│                                                                 │
│  Layer 5: Worker watchdog (supervisor-level)                    │
│  ├── Monitor thread checks worker health                        │
│  ├── Restart worker if critical state detected                  │
│  └── External: systemd/supervisor process restart               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation: Statement Timeout

```python
def _process_message(self, msg: Message) -> None:
    """Process with statement timeout protection."""
    with self._pool.connection() as conn:
        # PostgreSQL will kill queries exceeding this
        conn.execute(
            "SET statement_timeout = %s",
            (self._statement_timeout,)
        )
        try:
            with conn.transaction():
                self._handle(msg, conn)
        except psycopg.errors.QueryCanceled:
            # statement_timeout triggered
            logger.warning(
                "Query cancelled due to timeout: %s",
                msg.command_id
            )
            self._fail_transient(msg, "TIMEOUT", "Statement timeout exceeded")
```

### Implementation: Thread Abandonment

```python
def _wait_for_slot(self) -> None:
    """Wait for in-flight task to complete, with timeout."""
    with self._in_flight_lock:
        if not self._in_flight:
            self._stop_event.wait(self._poll_interval)
            return
        futures = list(self._in_flight.values())

    # Wait for any to complete
    done, _ = concurrent.futures.wait(
        futures,
        timeout=self._poll_interval,
        return_when=concurrent.futures.FIRST_COMPLETED,
    )

    # Check for stuck threads
    self._check_for_stuck_threads()

def _check_for_stuck_threads(self) -> None:
    """Identify and handle threads exceeding timeout."""
    now = time.monotonic()
    with self._in_flight_lock:
        for msg_id, (future, start_time) in list(self._in_flight.items()):
            elapsed = now - start_time
            if elapsed > self._visibility_timeout + 5:  # buffer
                logger.error(
                    "Thread stuck for %.1fs processing %s - abandoning",
                    elapsed, msg_id
                )
                # Don't cancel (may corrupt state), just stop tracking
                del self._in_flight[msg_id]
                self._health_status.record_stuck_thread()
```

---

## Connection Recovery Scenarios

### Scenario 1: Connection Becomes Invalid

**Cause:** Network blip, server restart, idle timeout

**Detection:** psycopg3 pool's `check` callback

**Recovery:**
```python
pool = ConnectionPool(
    ...,
    check=ConnectionPool.check_connection,  # Built-in validation
    max_lifetime=3600,  # Force refresh after 1 hour
)
```

The pool automatically:
1. Validates connections on checkout (`check`)
2. Discards broken connections
3. Creates new ones to maintain `min_size`

### Scenario 2: Transaction Left Open

**Cause:** Exception during processing, forgot commit/rollback

**Detection:** Pool checks connection state on return

**Recovery:**
```python
# psycopg3 pool behavior on putconn():
# - If connection in transaction: ROLLBACK issued automatically
# - If connection in error state: ROLLBACK issued
# - If connection broken: disposed and replaced
```

**Best Practice:** Always use context managers:
```python
with pool.connection() as conn:
    with conn.transaction():
        # ... work ...
        pass  # auto-commit on success, rollback on exception
```

### Scenario 3: Pool Exhaustion

**Cause:** All connections in use, more requests arrive

**Detection:** `PoolTimeout` exception after `timeout` seconds

**Recovery:**
```python
from psycopg_pool import PoolTimeout

def _get_connection_with_backoff(self) -> Connection:
    """Get connection with exponential backoff on exhaustion."""
    for attempt in range(3):
        try:
            return self._pool.getconn(timeout=10)
        except PoolTimeout:
            if attempt == 2:
                self._health_status.record_pool_exhaustion()
                raise
            backoff = 2 ** attempt
            logger.warning(
                "Pool exhausted, backing off %ds (attempt %d/3)",
                backoff, attempt + 1
            )
            time.sleep(backoff)
```

### Scenario 4: Database Unreachable

**Cause:** Network partition, database down, credentials expired

**Detection:** `reconnect_failed` callback after `reconnect_timeout`

**Recovery:**
```python
def on_reconnect_failed(pool: ConnectionPool) -> None:
    """Called when pool cannot reconnect within timeout."""
    logger.critical(
        "Database connection lost for %d seconds - entering degraded mode",
        pool.reconnect_timeout
    )
    # Options:
    # 1. Set health status to CRITICAL (for readiness probes)
    # 2. Trigger graceful shutdown
    # 3. Alert operators
    health_status.set_critical("database_unreachable")

pool = ConnectionPool(
    ...,
    reconnect_timeout=300,  # 5 minutes of retries
    reconnect_failed=on_reconnect_failed,
)
```

### Scenario 5: Connection Leaks

**Cause:** `getconn()` without matching `putconn()`

**Detection:** Pool size grows to `max_size`, new requests timeout

**Prevention:**
```python
# NEVER do this:
conn = pool.getconn()
# ... work ...
# forgot putconn()!

# ALWAYS do this:
with pool.connection() as conn:
    # ... work ...
    pass  # automatic putconn on exit
```

**Recovery:** Pool's `max_idle` causes leaked connections to expire eventually

---

## Worker Poisoning Scenarios

### Scenario 1: Handler Throws Uncaught Exception

**Impact:** Single message fails, thread returns to pool

**Recovery:** Automatic - exception stored in Future, worker continues

```python
def _on_complete(self, msg_id: str, future: Future) -> None:
    """Handle task completion."""
    with self._in_flight_lock:
        del self._in_flight[msg_id]

    try:
        future.result()  # Re-raises exception if any
    except Exception:
        logger.exception("Handler failed for %s", msg_id)
        # Message visibility timeout will cause retry
```

### Scenario 2: Handler Corrupts Thread State

**Impact:** Thread may behave incorrectly for subsequent tasks

**Example:** Setting thread-local that persists, changing locale

**Prevention:**
```python
# Isolate handler execution
def _process_message(self, msg: Message) -> None:
    """Process with clean state."""
    # Get fresh connection (no shared state)
    with self._pool.connection() as conn:
        # Connection-level settings reset on return to pool
        with conn.transaction():
            self._handle(msg, conn)
```

**Recovery:** ThreadPoolExecutor reuses threads - not easily recoverable. Consider:
1. ProcessPoolExecutor (process isolation, higher overhead)
2. Per-message thread creation (higher overhead)
3. Accept risk with good handler hygiene

### Scenario 3: Handler Deadlocks

**Impact:** Thread never returns, slot permanently consumed

**Detection:**
```python
class HealthStatus:
    def __init__(self):
        self._stuck_count = 0
        self._stuck_threshold = 3

    def record_stuck_thread(self) -> None:
        self._stuck_count += 1
        if self._stuck_count >= self._stuck_threshold:
            self._state = HealthState.CRITICAL

    def is_critical(self) -> bool:
        return self._state == HealthState.CRITICAL
```

**Recovery:** Worker watchdog triggers restart (see below)

### Scenario 4: Memory Leak in Handler

**Impact:** Worker process memory grows unbounded

**Detection:** External monitoring (Prometheus, memory limits)

**Recovery:**
1. Kubernetes memory limits trigger OOM kill + restart
2. systemd MemoryMax triggers restart
3. Application-level: periodic worker restart

```python
class SyncWorker:
    def __init__(self, ..., max_messages: int | None = 10000):
        self._max_messages = max_messages
        self._processed_count = 0

    def _should_restart(self) -> bool:
        if self._max_messages and self._processed_count >= self._max_messages:
            logger.info("Processed %d messages, requesting restart", self._processed_count)
            return True
        return False
```

### Scenario 5: Poison Message (Always Fails)

**Impact:** Message retried forever, consuming resources

**Prevention:** Max retry limit with exponential backoff

```python
# Already handled by RetryPolicy
retry_policy = RetryPolicy(
    max_attempts=5,
    backoff_schedule=[1, 5, 30, 120, 300],
)
# After max_attempts, message goes to TSQ
```

---

## Worker Self-Recovery Design

### Health Status Tracking

```python
from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime
import threading

class HealthState(Enum):
    HEALTHY = auto()
    DEGRADED = auto()
    CRITICAL = auto()

@dataclass
class HealthStatus:
    state: HealthState = HealthState.HEALTHY
    last_success: datetime | None = None
    consecutive_failures: int = 0
    stuck_threads: int = 0
    pool_exhaustions: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Thresholds
    FAILURE_THRESHOLD = 10
    STUCK_THRESHOLD = 3
    EXHAUSTION_THRESHOLD = 5

    def record_success(self) -> None:
        with self._lock:
            self.last_success = datetime.now()
            self.consecutive_failures = 0
            self._evaluate_state()

    def record_failure(self, error: Exception) -> None:
        with self._lock:
            self.consecutive_failures += 1
            self._evaluate_state()

    def record_stuck_thread(self) -> None:
        with self._lock:
            self.stuck_threads += 1
            self._evaluate_state()

    def record_pool_exhaustion(self) -> None:
        with self._lock:
            self.pool_exhaustions += 1
            self._evaluate_state()

    def _evaluate_state(self) -> None:
        if (self.stuck_threads >= self.STUCK_THRESHOLD or
            self.pool_exhaustions >= self.EXHAUSTION_THRESHOLD):
            self.state = HealthState.CRITICAL
        elif self.consecutive_failures >= self.FAILURE_THRESHOLD:
            self.state = HealthState.DEGRADED
        else:
            self.state = HealthState.HEALTHY
```

### Watchdog Thread Pattern

```python
class WorkerWatchdog:
    """Monitors worker health and triggers recovery actions."""

    def __init__(
        self,
        worker: SyncWorker,
        check_interval: float = 10.0,
        restart_callback: Callable[[], None] | None = None,
    ):
        self._worker = worker
        self._check_interval = check_interval
        self._restart_callback = restart_callback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="worker-watchdog",
            daemon=True,
        )
        self._thread.start()

    def _monitor_loop(self) -> None:
        while not self._stop_event.wait(self._check_interval):
            status = self._worker.health_status

            if status.state == HealthState.CRITICAL:
                logger.critical(
                    "Worker in CRITICAL state: stuck=%d, exhaustions=%d",
                    status.stuck_threads,
                    status.pool_exhaustions,
                )
                self._trigger_recovery()
            elif status.state == HealthState.DEGRADED:
                logger.warning(
                    "Worker in DEGRADED state: consecutive_failures=%d",
                    status.consecutive_failures,
                )

    def _trigger_recovery(self) -> None:
        """Attempt recovery actions."""
        logger.info("Initiating worker recovery")

        # Option 1: Request graceful restart
        if self._restart_callback:
            self._restart_callback()
            return

        # Option 2: Signal worker to stop (let supervisor restart)
        self._worker.stop()

        # Option 3: Hard exit (for systemd/supervisor to restart)
        # sys.exit(1)
```

### Integration with Process Supervisors

**systemd unit file:**
```ini
[Unit]
Description=CommandBus Worker
After=postgresql.service

[Service]
Type=simple
User=app
ExecStart=/app/venv/bin/python -m commandbus.worker
Restart=always
RestartSec=5
MemoryMax=512M
TimeoutStopSec=30

# Health check via sd_notify or HTTP endpoint
WatchdogSec=60
NotifyAccess=main

[Install]
WantedBy=multi-user.target
```

**Kubernetes deployment:**
```yaml
spec:
  containers:
  - name: worker
    livenessProbe:
      httpGet:
        path: /health/live
        port: 8080
      initialDelaySeconds: 10
      periodSeconds: 10
      failureThreshold: 3
    readinessProbe:
      httpGet:
        path: /health/ready
        port: 8080
      periodSeconds: 5
    resources:
      limits:
        memory: 512Mi
```

### Health Endpoint for Probes

```python
from fastapi import FastAPI, Response

app = FastAPI()

@app.get("/health/live")
def liveness():
    """Am I running at all?"""
    return {"status": "alive"}

@app.get("/health/ready")
def readiness(worker: SyncWorker = Depends(get_worker)):
    """Am I ready to process messages?"""
    status = worker.health_status

    if status.state == HealthState.CRITICAL:
        return Response(
            content='{"status": "critical"}',
            status_code=503,
            media_type="application/json",
        )
    elif status.state == HealthState.DEGRADED:
        return Response(
            content='{"status": "degraded"}',
            status_code=200,  # Still accept traffic
            media_type="application/json",
        )
    return {"status": "healthy"}
```

---

## Best Practices Summary

### Connection Pool

1. **Size pool for concurrency**: `min_size >= worker_concurrency`
2. **Enable connection validation**: `check=ConnectionPool.check_connection`
3. **Set reasonable lifetimes**: `max_lifetime=3600`, `max_idle=600`
4. **Handle reconnection failures**: Implement `reconnect_failed` callback
5. **Always use context managers**: `with pool.connection() as conn:`

### Timeouts

1. **Layer timeouts**: statement < visibility < thread < supervisor
2. **Set statement_timeout per-connection**: Prevents runaway queries
3. **Use pool timeout**: Fail fast on exhaustion
4. **Implement thread abandonment**: Don't let stuck threads block worker

### Worker Resilience

1. **Track health metrics**: Failures, stuck threads, pool exhaustions
2. **Implement watchdog**: Monitor and trigger recovery
3. **Support graceful shutdown**: Drain in-flight before exit
4. **Use process supervisors**: systemd, Kubernetes for restarts
5. **Expose health endpoints**: For liveness/readiness probes

### Handler Hygiene

1. **Keep handlers stateless**: No thread-local pollution
2. **Bound handler execution time**: Timeout at multiple layers
3. **Handle all exceptions**: Log and convert to retryable/permanent
4. **Limit retries**: Prevent poison messages

---

## Migration Strategy

### Phase 1: Foundation (Week 1-2)

1. Create `src/commandbus/sync/` package structure
2. Implement sync versions of repositories:
   - `SyncPgmqClient`
   - `SyncCommandRepository`
   - `SyncAuditLogger`
   - `SyncBatchRepository`
   - `SyncProcessRepository`
3. Unit tests for each sync repository

### Phase 2: Orchestration (Week 3-4)

1. Implement `SyncCommandBus` (native, not wrapper)
2. Implement `SyncWorker` with ThreadPoolExecutor
3. Implement `SyncProcessReplyRouter`
4. Integration tests with real PostgreSQL

### Phase 3: Health & Recovery (Week 5)

1. Implement `HealthStatus` tracking
2. Implement `WorkerWatchdog`
3. Add health endpoints to E2E app
4. Timeout and recovery tests

### Phase 4: Migration & Cleanup (Week 6)

1. Update E2E app to use native sync
2. Remove old sync wrappers (`SyncRuntime`, etc.)
3. Update documentation
4. Performance benchmarks

---

## File Changes Summary

### New Files

```
src/commandbus/sync/
├── __init__.py              # Public exports
├── pool.py                  # Pool configuration helpers
├── pgmq.py                  # SyncPgmqClient
├── repositories/
│   ├── __init__.py
│   ├── command.py           # SyncCommandRepository
│   ├── audit.py             # SyncAuditLogger
│   ├── batch.py             # SyncBatchRepository
│   └── process.py           # SyncProcessRepository
├── bus.py                   # SyncCommandBus (native)
├── worker.py                # SyncWorker (native)
├── process/
│   ├── __init__.py
│   ├── router.py            # SyncProcessReplyRouter
│   └── base.py              # SyncBaseProcessManager
├── health.py                # HealthStatus, HealthState
├── watchdog.py              # WorkerWatchdog
└── handler.py               # SyncHandlerRegistry
```

### Files to Remove

```
src/commandbus/sync/runtime.py    # Background event loop (DELETE)
src/commandbus/sync/config.py     # Thread pool config (MODIFY/DELETE)
```

### Files to Modify

```
src/commandbus/sync/__init__.py   # Update exports
tests/e2e/app/worker.py           # Use native sync components
tests/e2e/app/dependencies.py     # Update factory functions
```

---

## Success Criteria

1. **No connection pool exhaustion** under normal load
2. **Predictable resource usage**: connections = concurrency (not multiplied)
3. **Clean shutdown** within 30 seconds
4. **Self-recovery** from degraded states without manual intervention
5. **Health visibility** via metrics and health endpoints
6. **Performance parity** with async mode (within 10%)

---

## References

- [psycopg3 Connection Pools](https://www.psycopg.org/psycopg3/docs/advanced/pool.html)
- [psycopg3 Pool API](https://www.psycopg.org/psycopg3/docs/api/pool.html)
- [Python concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html)
- [ThreadPoolExecutor Guide](https://superfastpython.com/threadpoolexecutor-in-python/)
- [Watchdog Thread Pattern](https://superfastpython.com/watchdog-thread-in-python/)
- [PostgreSQL statement_timeout](https://www.postgresql.org/docs/current/runtime-config-client.html)
- [Designing psycopg3 Pool](https://www.psycopg.org/articles/2021/01/17/pool-design/)
