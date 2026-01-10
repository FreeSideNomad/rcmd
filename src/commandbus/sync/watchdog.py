"""Worker watchdog for monitoring and recovery.

This module provides a watchdog that monitors worker health status and
triggers recovery actions when workers enter critical states.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from commandbus.sync.health import HealthStatus

logger = logging.getLogger(__name__)


class Watchable(Protocol):
    """Protocol for objects that can be monitored by the watchdog.

    Any worker or router with a health_status property and stop method
    can be monitored by the WorkerWatchdog.
    """

    @property
    def health_status(self) -> HealthStatus:
        """Get the health status tracker."""
        ...

    def stop(self, timeout: float | None = None) -> None:
        """Stop the worker gracefully."""
        ...


class WorkerWatchdog:
    """Monitors worker health and triggers recovery actions.

    The watchdog runs a daemon thread that periodically checks the health
    status of monitored workers. When a worker enters a critical state,
    the watchdog can trigger a restart callback or stop the worker.

    Example:
        worker = SyncWorker(pool, domain="payments", registry=registry)

        def restart_worker():
            worker.stop()
            # Restart logic here

        watchdog = WorkerWatchdog(
            worker,
            check_interval=10.0,
            restart_callback=restart_worker,
        )
        watchdog.start()

        # Run worker
        try:
            worker.run(concurrency=4)
        finally:
            watchdog.stop()
    """

    def __init__(
        self,
        worker: Watchable,
        *,
        check_interval: float = 10.0,
        restart_callback: Callable[[], None] | None = None,
        name: str | None = None,
    ) -> None:
        """Initialize the worker watchdog.

        Args:
            worker: The worker to monitor (must have health_status property)
            check_interval: Seconds between health checks
            restart_callback: Optional callback to trigger on CRITICAL state.
                             If not provided, worker.stop() will be called.
            name: Optional name for the watchdog thread
        """
        self._worker = worker
        self._check_interval = check_interval
        self._restart_callback = restart_callback
        self._name = name or "worker-watchdog"

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._recovery_triggered = False

    @property
    def is_running(self) -> bool:
        """Check if the watchdog is currently running."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def recovery_triggered(self) -> bool:
        """Check if recovery has been triggered."""
        return self._recovery_triggered

    def start(self) -> None:
        """Start the watchdog monitoring thread.

        The thread runs as a daemon so it won't prevent program exit.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Watchdog already running")
            return

        self._stop_event.clear()
        self._recovery_triggered = False
        self._thread = threading.Thread(
            target=self._monitor_loop,
            name=self._name,
            daemon=True,
        )
        self._thread.start()
        logger.info(f"Started watchdog '{self._name}' with {self._check_interval}s interval")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the watchdog monitoring thread.

        Args:
            timeout: Maximum seconds to wait for thread to exit
        """
        if self._thread is None:
            return

        logger.info(f"Stopping watchdog '{self._name}'...")
        self._stop_event.set()

        if self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(f"Watchdog '{self._name}' did not stop within timeout")

        self._thread = None
        logger.info(f"Watchdog '{self._name}' stopped")

    def _monitor_loop(self) -> None:
        """Main monitoring loop - check health periodically."""
        while not self._stop_event.wait(timeout=self._check_interval):
            try:
                self._check_health()
            except Exception:
                logger.exception(f"Error in watchdog '{self._name}' health check")

    def _check_health(self) -> None:
        """Check worker health and take action if needed."""
        status = self._worker.health_status

        if status.is_critical:
            logger.error(
                f"Watchdog '{self._name}' detected CRITICAL state: "
                f"stuck_threads={status.stuck_threads}, "
                f"pool_exhaustions={status.pool_exhaustions}, "
                f"consecutive_failures={status.consecutive_failures}"
            )
            self._trigger_recovery()
        elif status.is_degraded:
            logger.warning(
                f"Watchdog '{self._name}' detected DEGRADED state: "
                f"consecutive_failures={status.consecutive_failures}"
            )
            # Don't trigger recovery for degraded state, just log
        else:
            logger.debug(f"Watchdog '{self._name}' health check: HEALTHY")

    def _trigger_recovery(self) -> None:
        """Trigger recovery action for critical state."""
        if self._recovery_triggered:
            logger.warning(f"Watchdog '{self._name}' recovery already triggered, skipping")
            return

        self._recovery_triggered = True
        logger.warning(f"Watchdog '{self._name}' triggering recovery action")

        if self._restart_callback is not None:
            try:
                self._restart_callback()
            except Exception:
                logger.exception(f"Error in watchdog '{self._name}' restart callback")
        else:
            # Default: just stop the worker
            try:
                self._worker.stop()
            except Exception:
                logger.exception(f"Error stopping worker from watchdog '{self._name}'")
