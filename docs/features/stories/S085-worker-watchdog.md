# S085: Worker Watchdog

## User Story

As a system operator, I want a watchdog thread that monitors worker health and triggers recovery so that workers self-heal without manual intervention.

## Acceptance Criteria

### AC1: WorkerWatchdog Class
- Given a SyncWorker
- When I create `WorkerWatchdog(worker, check_interval=10)`
- Then watchdog is configured to monitor worker

### AC2: start() Method
- Given watchdog created
- When I call `start()`
- Then daemon thread starts monitoring

### AC3: Health Check Loop
- Given watchdog running
- When check_interval elapses
- Then worker.health_status is evaluated

### AC4: CRITICAL Recovery
- Given worker health is CRITICAL
- When watchdog detects state
- Then it calls restart_callback or worker.stop()

### AC5: DEGRADED Warning
- Given worker health is DEGRADED
- When watchdog detects state
- Then it logs warning but doesn't trigger restart

### AC6: stop() Method
- Given watchdog running
- When stop() called
- Then monitoring thread exits cleanly

## Implementation Notes

**File:** `src/commandbus/sync/watchdog.py`

**Code Pattern:**
```python
import logging
import threading
from typing import Callable, Any

from commandbus.sync.health import HealthState

logger = logging.getLogger(__name__)


class WorkerWatchdog:
    """Monitors worker health and triggers recovery actions.

    The watchdog runs as a daemon thread, periodically checking
    the worker's health status. When critical state is detected,
    it can trigger a restart or graceful shutdown.

    Usage:
        worker = SyncWorker(...)
        watchdog = WorkerWatchdog(worker, check_interval=10.0)
        watchdog.start()

        # Later, when shutting down:
        watchdog.stop()
    """

    def __init__(
        self,
        worker: Any,  # SyncWorker or similar with health_status property
        check_interval: float = 10.0,
        restart_callback: Callable[[], None] | None = None,
    ):
        """Initialize watchdog.

        Args:
            worker: Worker instance with health_status property
            check_interval: Seconds between health checks
            restart_callback: Optional callback to trigger restart.
                             If None, worker.stop() is called on critical state.
        """
        self._worker = worker
        self._check_interval = check_interval
        self._restart_callback = restart_callback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the watchdog monitoring thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Watchdog already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name="worker-watchdog",
            daemon=True,
        )
        self._thread.start()
        logger.info("Watchdog started with check_interval=%.1fs", self._check_interval)

    def stop(self) -> None:
        """Stop the watchdog monitoring thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("Watchdog stopped")

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while not self._stop_event.wait(self._check_interval):
            self._check_health()

    def _check_health(self) -> None:
        """Check worker health and take action if needed."""
        try:
            status = self._worker.health_status
        except Exception:
            logger.exception("Error reading worker health status")
            return

        if status.state == HealthState.CRITICAL:
            logger.critical(
                "Worker in CRITICAL state: stuck_threads=%d, pool_exhaustions=%d",
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
        """Trigger recovery action."""
        logger.info("Initiating worker recovery")

        if self._restart_callback is not None:
            try:
                self._restart_callback()
            except Exception:
                logger.exception("Restart callback failed")
        else:
            # Default: signal worker to stop (let supervisor restart)
            try:
                self._worker.stop()
            except Exception:
                logger.exception("Failed to stop worker")
```

**Estimated Lines:** ~60 new
