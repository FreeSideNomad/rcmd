# S084: Health Status Tracking

## User Story

As a system operator, I want workers to track their health status so that monitoring systems can detect degraded or critical states.

## Acceptance Criteria

### AC1: HealthState Enum
- Given health monitoring is needed
- When I use HealthState
- Then I have: HEALTHY, DEGRADED, CRITICAL

### AC2: HealthStatus Dataclass
- Given worker health tracking is needed
- When I use HealthStatus
- Then it tracks: state, last_success, consecutive_failures, stuck_threads, pool_exhaustions

### AC3: Thread Safety
- Given multiple worker threads update health
- When updates occur concurrently
- Then Lock ensures consistent state

### AC4: Threshold Transitions
- Given consecutive_failures >= 10
- Then state becomes DEGRADED
- Given stuck_threads >= 3 OR pool_exhaustions >= 5
- Then state becomes CRITICAL

### AC5: Recovery Path
- Given state is DEGRADED
- When record_success() called
- Then consecutive_failures resets and state may return to HEALTHY

### AC6: Metrics Export
- Given health status tracked
- When metrics endpoint queried
- Then current state and counters returned as dict

## Implementation Notes

**File:** `src/commandbus/sync/health.py`

**Code Pattern:**
```python
from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime
import threading
from typing import Any

class HealthState(Enum):
    """Worker health states."""
    HEALTHY = auto()
    DEGRADED = auto()
    CRITICAL = auto()


@dataclass
class HealthStatus:
    """Thread-safe worker health status tracking.

    Tracks various failure modes and transitions between health states
    based on configurable thresholds.
    """
    state: HealthState = HealthState.HEALTHY
    last_success: datetime | None = None
    consecutive_failures: int = 0
    stuck_threads: int = 0
    pool_exhaustions: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # Thresholds for state transitions
    FAILURE_THRESHOLD: int = 10
    STUCK_THRESHOLD: int = 3
    EXHAUSTION_THRESHOLD: int = 5

    def record_success(self) -> None:
        """Record successful message processing."""
        with self._lock:
            self.last_success = datetime.now()
            self.consecutive_failures = 0
            self._evaluate_state()

    def record_failure(self, error: Exception) -> None:
        """Record processing failure."""
        with self._lock:
            self.consecutive_failures += 1
            self._evaluate_state()

    def record_stuck_thread(self) -> None:
        """Record a thread that exceeded timeout and was abandoned."""
        with self._lock:
            self.stuck_threads += 1
            self._evaluate_state()

    def record_pool_exhaustion(self) -> None:
        """Record connection pool exhaustion event."""
        with self._lock:
            self.pool_exhaustions += 1
            self._evaluate_state()

    def reset_counters(self) -> None:
        """Reset all counters (e.g., after recovery)."""
        with self._lock:
            self.consecutive_failures = 0
            self.stuck_threads = 0
            self.pool_exhaustions = 0
            self._evaluate_state()

    def _evaluate_state(self) -> None:
        """Evaluate and update health state based on current metrics."""
        if (self.stuck_threads >= self.STUCK_THRESHOLD or
            self.pool_exhaustions >= self.EXHAUSTION_THRESHOLD):
            self.state = HealthState.CRITICAL
        elif self.consecutive_failures >= self.FAILURE_THRESHOLD:
            self.state = HealthState.DEGRADED
        else:
            self.state = HealthState.HEALTHY

    def is_healthy(self) -> bool:
        """Check if worker is in healthy state."""
        with self._lock:
            return self.state == HealthState.HEALTHY

    def is_critical(self) -> bool:
        """Check if worker is in critical state."""
        with self._lock:
            return self.state == HealthState.CRITICAL

    def to_dict(self) -> dict[str, Any]:
        """Export health status as dictionary for metrics/API."""
        with self._lock:
            return {
                "state": self.state.name,
                "last_success": self.last_success.isoformat() if self.last_success else None,
                "consecutive_failures": self.consecutive_failures,
                "stuck_threads": self.stuck_threads,
                "pool_exhaustions": self.pool_exhaustions,
            }
```

**Estimated Lines:** ~80 new
