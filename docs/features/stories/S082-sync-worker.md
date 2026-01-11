# S082: Sync Worker

## User Story

As a system operator, I want a native synchronous worker that uses ThreadPoolExecutor for concurrency so that sync handlers execute efficiently without async overhead.

## Acceptance Criteria

### AC1: SyncWorker Class
- Given sync pool, domain, and registry
- When I create `SyncWorker(pool, domain, registry, concurrency=4)`
- Then worker is configured with thread pool executor

### AC2: run() Method
- Given worker is configured
- When I call `run()` (blocking)
- Then worker polls queue and dispatches to thread pool until stop() called

### AC3: Concurrency Control
- Given concurrency=N
- When N messages are being processed
- Then no new messages are read until slot available

### AC4: Statement Timeout
- Given statement_timeout configured
- When handler query exceeds timeout
- Then PostgreSQL cancels query and QueryCanceled raised

### AC5: Thread Naming
- Given thread pool created
- When threads execute
- Then thread names are `worker-{domain}-{n}` for debugging

### AC6: Graceful Shutdown
- Given `stop()` is called
- When in-flight messages exist
- Then worker drains in-flight tasks before exiting (up to drain timeout)

### AC7: Health Status Integration
- Given failures occur
- When consecutive failures exceed threshold
- Then health status transitions to DEGRADED

### AC8: Message Visibility
- Given message read with visibility_timeout
- When processing completes within timeout
- Then message deleted; otherwise message becomes visible again

## Implementation Notes

**File:** `src/commandbus/sync/worker.py`

**Key Differences from Async:**

| Async Worker | Sync Worker |
|--------------|-------------|
| `asyncio.Semaphore` | slot counting with Lock |
| `asyncio.Event` | `threading.Event` |
| `asyncio.Task` | `concurrent.futures.Future` |
| `asyncio.gather` | `concurrent.futures.wait` |
| `asyncio.create_task` | `executor.submit` |
| `await conn.notifies()` | polling with timeout |

**Code Pattern:**
```python
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
from psycopg_pool import ConnectionPool
from psycopg import Connection
import psycopg.errors
from commandbus.handler import HandlerRegistry
from commandbus.sync.health import HealthStatus, HealthState
from commandbus.sync.pgmq import SyncPgmqClient
from commandbus.sync.repositories.command import SyncCommandRepository

logger = logging.getLogger(__name__)

class SyncWorker:
    def __init__(
        self,
        pool: ConnectionPool,
        domain: str,
        registry: HandlerRegistry,
        *,
        concurrency: int = 4,
        poll_interval: float = 1.0,
        visibility_timeout: int = 30,
        statement_timeout: int = 25000,
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
        self._in_flight: dict[str, tuple[Future, float]] = {}
        self._in_flight_lock = threading.Lock()
        self._health = HealthStatus()

        self._pgmq = SyncPgmqClient(pool)
        self._repo = SyncCommandRepository(pool)

    @property
    def health_status(self) -> HealthStatus:
        return self._health

    def run(self) -> None:
        """Main worker loop - blocks until stop() called."""
        self._executor = ThreadPoolExecutor(
            max_workers=self._concurrency,
            thread_name_prefix=f"worker-{self._domain}",
        )
        logger.info(
            "Starting sync worker for %s with concurrency=%d",
            self._domain, self._concurrency
        )
        try:
            while not self._stop_event.is_set():
                self._poll_and_dispatch()
        finally:
            self._drain_in_flight()
            self._executor.shutdown(wait=True)
            logger.info("Sync worker for %s stopped", self._domain)

    def stop(self) -> None:
        """Signal worker to stop."""
        self._stop_event.set()

    def _poll_and_dispatch(self) -> None:
        """Read messages and dispatch to thread pool."""
        with self._in_flight_lock:
            available = self._concurrency - len(self._in_flight)

        if available <= 0:
            self._wait_for_slot()
            return

        queue_name = f"{self._domain}__commands"
        messages = self._pgmq.read(
            queue_name,
            vt=self._visibility_timeout,
            limit=available,
        )

        if not messages:
            self._stop_event.wait(self._poll_interval)
            return

        for msg in messages:
            future = self._executor.submit(self._process_message, msg)
            with self._in_flight_lock:
                self._in_flight[str(msg.msg_id)] = (future, time.monotonic())
            future.add_done_callback(
                lambda f, mid=str(msg.msg_id): self._on_complete(mid, f)
            )

    def _process_message(self, msg) -> None:
        """Process single message with dedicated connection."""
        with self._pool.connection() as conn:
            conn.execute(f"SET statement_timeout = {self._statement_timeout}")
            try:
                with conn.transaction():
                    self._handle(msg, conn)
                    self._health.record_success()
            except psycopg.errors.QueryCanceled:
                logger.warning("Statement timeout for message %s", msg.msg_id)
                self._health.record_failure(Exception("Statement timeout"))
            except Exception as e:
                logger.exception("Error processing message %s", msg.msg_id)
                self._health.record_failure(e)
                raise

    def _wait_for_slot(self) -> None:
        """Wait for in-flight task to complete."""
        with self._in_flight_lock:
            if not self._in_flight:
                self._stop_event.wait(self._poll_interval)
                return
            futures = [f for f, _ in self._in_flight.values()]

        done, _ = wait(futures, timeout=self._poll_interval, return_when=FIRST_COMPLETED)
        self._check_stuck_threads()

    def _check_stuck_threads(self) -> None:
        """Identify threads exceeding timeout."""
        now = time.monotonic()
        stuck_threshold = self._visibility_timeout + 5

        with self._in_flight_lock:
            for msg_id, (future, start_time) in list(self._in_flight.items()):
                elapsed = now - start_time
                if elapsed > stuck_threshold:
                    logger.error(
                        "Thread stuck for %.1fs processing %s - abandoning",
                        elapsed, msg_id
                    )
                    del self._in_flight[msg_id]
                    self._health.record_stuck_thread()

    def _on_complete(self, msg_id: str, future: Future) -> None:
        """Handle task completion."""
        with self._in_flight_lock:
            self._in_flight.pop(msg_id, None)

        try:
            future.result()
        except Exception:
            logger.exception("Handler failed for %s", msg_id)

    def _drain_in_flight(self) -> None:
        """Wait for all in-flight tasks to complete."""
        with self._in_flight_lock:
            futures = [f for f, _ in self._in_flight.values()]

        if futures:
            logger.info("Draining %d in-flight tasks", len(futures))
            wait(futures, timeout=self._visibility_timeout)
```

**Estimated Lines:** ~400 new
