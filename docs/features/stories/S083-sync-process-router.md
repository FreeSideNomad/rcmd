# S083: Sync Process Reply Router

## User Story

As a system operator, I want a native synchronous process reply router so that process managers receive replies without async overhead.

## Acceptance Criteria

### AC1: SyncProcessReplyRouter Class
- Given sync pool, process repo, and managers dict
- When I create `SyncProcessReplyRouter(pool, process_repo, managers, reply_queue)`
- Then router is configured to dispatch replies

### AC2: run() Method
- Given router is configured
- When I call `run(concurrency, poll_interval)`
- Then router polls reply queue and dispatches using thread pool

### AC3: Reply Dispatch
- Given reply with correlation_id
- When router processes reply
- Then it looks up process and calls `manager.handle_reply(reply, process)`

### AC4: Unknown Process Handling
- Given correlation_id doesn't match any process
- When router processes reply
- Then it logs warning and deletes message

### AC5: Stop and Drain
- Given `stop()` is called
- When in-flight dispatches exist
- Then router drains before exiting

## Implementation Notes

**File:** `src/commandbus/sync/process/router.py`

**Similar to SyncWorker but:**
- Dispatches to ProcessManager.handle_reply() instead of handler
- Lookup process by correlation_id before dispatch
- Uses same ThreadPoolExecutor pattern

**Code Pattern:**
```python
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
from uuid import UUID
from psycopg_pool import ConnectionPool
from commandbus.sync.pgmq import SyncPgmqClient
from commandbus.sync.process.repository import SyncProcessRepository
from commandbus.sync.health import HealthStatus

logger = logging.getLogger(__name__)

class SyncProcessReplyRouter:
    def __init__(
        self,
        pool: ConnectionPool,
        process_repo: SyncProcessRepository,
        managers: dict[str, Any],
        reply_queue: str,
        domain: str,
        *,
        concurrency: int = 4,
        poll_interval: float = 1.0,
        visibility_timeout: int = 30,
    ):
        self._pool = pool
        self._process_repo = process_repo
        self._managers = managers
        self._reply_queue = reply_queue
        self._domain = domain
        self._concurrency = concurrency
        self._poll_interval = poll_interval
        self._visibility_timeout = visibility_timeout

        self._executor: ThreadPoolExecutor | None = None
        self._stop_event = threading.Event()
        self._in_flight: dict[str, tuple[Future, float]] = {}
        self._in_flight_lock = threading.Lock()
        self._health = HealthStatus()

        self._pgmq = SyncPgmqClient(pool)

    @property
    def health_status(self) -> HealthStatus:
        return self._health

    def run(self, concurrency: int | None = None, poll_interval: float | None = None) -> None:
        """Main router loop - blocks until stop() called."""
        effective_concurrency = concurrency or self._concurrency
        effective_poll = poll_interval or self._poll_interval

        self._executor = ThreadPoolExecutor(
            max_workers=effective_concurrency,
            thread_name_prefix=f"router-{self._domain}",
        )
        logger.info(
            "Starting sync process router for %s with concurrency=%d",
            self._reply_queue, effective_concurrency
        )
        try:
            while not self._stop_event.is_set():
                self._poll_and_dispatch(effective_poll)
        finally:
            self._drain_in_flight()
            self._executor.shutdown(wait=True)
            logger.info("Sync process router for %s stopped", self._reply_queue)

    def stop(self) -> None:
        """Signal router to stop."""
        self._stop_event.set()

    def _poll_and_dispatch(self, poll_interval: float) -> None:
        """Read replies and dispatch to process managers."""
        with self._in_flight_lock:
            available = self._concurrency - len(self._in_flight)

        if available <= 0:
            self._wait_for_slot(poll_interval)
            return

        messages = self._pgmq.read(
            self._reply_queue,
            vt=self._visibility_timeout,
            limit=available,
        )

        if not messages:
            self._stop_event.wait(poll_interval)
            return

        for msg in messages:
            future = self._executor.submit(self._dispatch_reply, msg)
            with self._in_flight_lock:
                self._in_flight[str(msg.msg_id)] = (future, time.monotonic())
            future.add_done_callback(
                lambda f, mid=str(msg.msg_id): self._on_complete(mid, f)
            )

    def _dispatch_reply(self, msg) -> None:
        """Dispatch reply to appropriate process manager."""
        correlation_id = msg.message.get("correlation_id")
        if not correlation_id:
            logger.warning("Reply missing correlation_id: %s", msg.msg_id)
            self._pgmq.delete(self._reply_queue, msg.msg_id)
            return

        process_id = UUID(correlation_id)
        process = self._process_repo.get_by_id(self._domain, process_id)

        if process is None:
            logger.warning(
                "No process found for correlation_id %s, deleting reply",
                correlation_id
            )
            self._pgmq.delete(self._reply_queue, msg.msg_id)
            return

        manager = self._managers.get(process.process_type)
        if manager is None:
            logger.error(
                "No manager registered for process_type %s",
                process.process_type
            )
            self._pgmq.delete(self._reply_queue, msg.msg_id)
            return

        try:
            manager.handle_reply(msg.message, process)
            self._pgmq.delete(self._reply_queue, msg.msg_id)
            self._health.record_success()
        except Exception as e:
            logger.exception(
                "Error handling reply for process %s: %s",
                process_id, e
            )
            self._health.record_failure(e)
            # Leave message for retry via visibility timeout

    def _wait_for_slot(self, poll_interval: float) -> None:
        """Wait for in-flight task to complete."""
        with self._in_flight_lock:
            if not self._in_flight:
                self._stop_event.wait(poll_interval)
                return
            futures = [f for f, _ in self._in_flight.values()]

        wait(futures, timeout=poll_interval, return_when=FIRST_COMPLETED)

    def _on_complete(self, msg_id: str, future: Future) -> None:
        """Handle task completion."""
        with self._in_flight_lock:
            self._in_flight.pop(msg_id, None)

        try:
            future.result()
        except Exception:
            logger.exception("Reply dispatch failed for %s", msg_id)

    def _drain_in_flight(self) -> None:
        """Wait for all in-flight tasks to complete."""
        with self._in_flight_lock:
            futures = [f for f, _ in self._in_flight.values()]

        if futures:
            logger.info("Draining %d in-flight dispatches", len(futures))
            wait(futures, timeout=self._visibility_timeout)
```

**Estimated Lines:** ~200 new
