"""Health status tracking for sync workers.

This module provides thread-safe health status tracking for synchronous
workers, enabling monitoring systems to detect degraded or critical states.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any


class HealthState(Enum):
    """Health states for workers.

    HEALTHY: Worker is operating normally
    DEGRADED: Worker is experiencing issues but still functional
    CRITICAL: Worker is in a critical state requiring intervention
    """

    HEALTHY = auto()
    DEGRADED = auto()
    CRITICAL = auto()


@dataclass
class HealthStatus:
    """Thread-safe health status tracking.

    Tracks worker health including:
    - Consecutive failures count
    - Stuck threads count
    - Pool exhaustion events
    - Last success timestamp

    State transitions:
    - HEALTHY → DEGRADED: When consecutive_failures >= FAILURE_THRESHOLD
    - HEALTHY/DEGRADED → CRITICAL: When stuck_threads >= STUCK_THRESHOLD
                                   OR pool_exhaustions >= EXHAUSTION_THRESHOLD
    - DEGRADED → HEALTHY: When record_success() resets consecutive_failures

    Example:
        status = HealthStatus()

        # Record success
        status.record_success()
        assert status.state == HealthState.HEALTHY

        # Record failures
        for _ in range(10):
            status.record_failure(Exception("test"))
        assert status.state == HealthState.DEGRADED

        # Record stuck thread
        status.record_stuck_thread()
        status.record_stuck_thread()
        status.record_stuck_thread()
        assert status.state == HealthState.CRITICAL
    """

    # Thresholds for state transitions
    FAILURE_THRESHOLD: int = 10
    STUCK_THRESHOLD: int = 3
    EXHAUSTION_THRESHOLD: int = 5

    # State fields
    state: HealthState = HealthState.HEALTHY
    last_success: datetime | None = None
    consecutive_failures: int = 0
    stuck_threads: int = 0
    pool_exhaustions: int = 0
    total_successes: int = 0
    total_failures: int = 0

    # Thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self) -> None:
        """Record a successful operation.

        Resets consecutive_failures and updates last_success timestamp.
        May transition state from DEGRADED to HEALTHY.
        """
        with self._lock:
            self.last_success = datetime.now(UTC)
            self.consecutive_failures = 0
            self.total_successes += 1
            self._evaluate_state()

    def record_failure(self, error: Exception | None = None) -> None:  # noqa: ARG002
        """Record a failed operation.

        Increments consecutive_failures counter.
        May transition state to DEGRADED.

        Args:
            error: Optional exception that caused the failure (for logging)
        """
        with self._lock:
            self.consecutive_failures += 1
            self.total_failures += 1
            self._evaluate_state()

    def record_stuck_thread(self) -> None:
        """Record a stuck thread detection.

        Increments stuck_threads counter.
        May transition state to CRITICAL.
        """
        with self._lock:
            self.stuck_threads += 1
            self._evaluate_state()

    def record_pool_exhaustion(self) -> None:
        """Record a pool exhaustion event.

        Increments pool_exhaustions counter.
        May transition state to CRITICAL.
        """
        with self._lock:
            self.pool_exhaustions += 1
            self._evaluate_state()

    def reset_stuck_threads(self) -> None:
        """Reset stuck threads counter.

        Called after recovery action to allow state re-evaluation.
        """
        with self._lock:
            self.stuck_threads = 0
            self._evaluate_state()

    def reset_pool_exhaustions(self) -> None:
        """Reset pool exhaustions counter.

        Called after recovery action to allow state re-evaluation.
        """
        with self._lock:
            self.pool_exhaustions = 0
            self._evaluate_state()

    def reset(self) -> None:
        """Reset all counters and state to healthy.

        Used after a full worker restart.
        """
        with self._lock:
            self.state = HealthState.HEALTHY
            self.consecutive_failures = 0
            self.stuck_threads = 0
            self.pool_exhaustions = 0
            # Keep totals and last_success for historical tracking

    def _evaluate_state(self) -> None:
        """Evaluate and update health state based on current counters.

        Called internally after each counter update.
        Must be called with lock held.
        """
        # Critical conditions take precedence
        if (
            self.stuck_threads >= self.STUCK_THRESHOLD
            or self.pool_exhaustions >= self.EXHAUSTION_THRESHOLD
        ):
            self.state = HealthState.CRITICAL
        elif self.consecutive_failures >= self.FAILURE_THRESHOLD:
            self.state = HealthState.DEGRADED
        else:
            self.state = HealthState.HEALTHY

    def to_dict(self) -> dict[str, Any]:
        """Export health status as dictionary for metrics/monitoring.

        Returns:
            Dictionary with current health state and all counters.
        """
        with self._lock:
            return {
                "state": self.state.name,
                "last_success": self.last_success.isoformat() if self.last_success else None,
                "consecutive_failures": self.consecutive_failures,
                "stuck_threads": self.stuck_threads,
                "pool_exhaustions": self.pool_exhaustions,
                "total_successes": self.total_successes,
                "total_failures": self.total_failures,
            }

    @property
    def is_healthy(self) -> bool:
        """Check if worker is in healthy state."""
        with self._lock:
            return self.state == HealthState.HEALTHY

    @property
    def is_degraded(self) -> bool:
        """Check if worker is in degraded state."""
        with self._lock:
            return self.state == HealthState.DEGRADED

    @property
    def is_critical(self) -> bool:
        """Check if worker is in critical state."""
        with self._lock:
            return self.state == HealthState.CRITICAL
