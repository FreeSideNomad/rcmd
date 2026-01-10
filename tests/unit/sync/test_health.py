"""Unit tests for commandbus.sync.health module."""

import threading
from concurrent.futures import ThreadPoolExecutor

from commandbus.sync.health import HealthState, HealthStatus


class TestHealthState:
    """Tests for HealthState enum."""

    def test_health_states_defined(self) -> None:
        """All health states should be defined."""
        assert HealthState.HEALTHY is not None
        assert HealthState.DEGRADED is not None
        assert HealthState.CRITICAL is not None

    def test_health_states_unique(self) -> None:
        """Health states should have unique values."""
        states = [HealthState.HEALTHY, HealthState.DEGRADED, HealthState.CRITICAL]
        values = [s.value for s in states]
        assert len(values) == len(set(values))


class TestHealthStatusInit:
    """Tests for HealthStatus initialization."""

    def test_default_state_is_healthy(self) -> None:
        """Default state should be HEALTHY."""
        status = HealthStatus()
        assert status.state == HealthState.HEALTHY

    def test_default_counters_are_zero(self) -> None:
        """Default counters should be zero."""
        status = HealthStatus()
        assert status.consecutive_failures == 0
        assert status.stuck_threads == 0
        assert status.pool_exhaustions == 0
        assert status.total_successes == 0
        assert status.total_failures == 0

    def test_default_last_success_is_none(self) -> None:
        """Default last_success should be None."""
        status = HealthStatus()
        assert status.last_success is None

    def test_thresholds_defined(self) -> None:
        """Thresholds should be defined with sensible defaults."""
        status = HealthStatus()
        assert status.FAILURE_THRESHOLD == 10
        assert status.STUCK_THRESHOLD == 3
        assert status.EXHAUSTION_THRESHOLD == 5


class TestHealthStatusRecordSuccess:
    """Tests for HealthStatus.record_success method."""

    def test_record_success_updates_last_success(self) -> None:
        """record_success should update last_success timestamp."""
        status = HealthStatus()
        assert status.last_success is None

        status.record_success()

        assert status.last_success is not None

    def test_record_success_increments_total(self) -> None:
        """record_success should increment total_successes."""
        status = HealthStatus()

        status.record_success()
        status.record_success()

        assert status.total_successes == 2

    def test_record_success_resets_consecutive_failures(self) -> None:
        """record_success should reset consecutive_failures."""
        status = HealthStatus()
        status.consecutive_failures = 5

        status.record_success()

        assert status.consecutive_failures == 0

    def test_record_success_can_recover_from_degraded(self) -> None:
        """record_success should transition from DEGRADED to HEALTHY."""
        status = HealthStatus()
        # Manually set degraded state
        status.consecutive_failures = 10
        status._evaluate_state()
        assert status.state == HealthState.DEGRADED

        status.record_success()

        assert status.state == HealthState.HEALTHY


class TestHealthStatusRecordFailure:
    """Tests for HealthStatus.record_failure method."""

    def test_record_failure_increments_consecutive(self) -> None:
        """record_failure should increment consecutive_failures."""
        status = HealthStatus()

        status.record_failure()
        assert status.consecutive_failures == 1

        status.record_failure()
        assert status.consecutive_failures == 2

    def test_record_failure_increments_total(self) -> None:
        """record_failure should increment total_failures."""
        status = HealthStatus()

        status.record_failure()
        status.record_failure()

        assert status.total_failures == 2

    def test_record_failure_accepts_exception(self) -> None:
        """record_failure should accept optional exception."""
        status = HealthStatus()

        status.record_failure(ValueError("test error"))

        assert status.consecutive_failures == 1

    def test_record_failure_transitions_to_degraded(self) -> None:
        """record_failure should transition to DEGRADED after threshold."""
        status = HealthStatus()

        for _ in range(9):
            status.record_failure()
            assert status.state == HealthState.HEALTHY

        status.record_failure()  # 10th failure
        assert status.state == HealthState.DEGRADED


class TestHealthStatusRecordStuckThread:
    """Tests for HealthStatus.record_stuck_thread method."""

    def test_record_stuck_thread_increments_counter(self) -> None:
        """record_stuck_thread should increment stuck_threads."""
        status = HealthStatus()

        status.record_stuck_thread()
        assert status.stuck_threads == 1

        status.record_stuck_thread()
        assert status.stuck_threads == 2

    def test_record_stuck_thread_transitions_to_critical(self) -> None:
        """record_stuck_thread should transition to CRITICAL after threshold."""
        status = HealthStatus()

        status.record_stuck_thread()
        status.record_stuck_thread()
        assert status.state == HealthState.HEALTHY

        status.record_stuck_thread()  # 3rd stuck thread
        assert status.state == HealthState.CRITICAL


class TestHealthStatusRecordPoolExhaustion:
    """Tests for HealthStatus.record_pool_exhaustion method."""

    def test_record_pool_exhaustion_increments_counter(self) -> None:
        """record_pool_exhaustion should increment pool_exhaustions."""
        status = HealthStatus()

        status.record_pool_exhaustion()
        assert status.pool_exhaustions == 1

        status.record_pool_exhaustion()
        assert status.pool_exhaustions == 2

    def test_record_pool_exhaustion_transitions_to_critical(self) -> None:
        """record_pool_exhaustion should transition to CRITICAL after threshold."""
        status = HealthStatus()

        for _ in range(4):
            status.record_pool_exhaustion()
            assert status.state == HealthState.HEALTHY

        status.record_pool_exhaustion()  # 5th exhaustion
        assert status.state == HealthState.CRITICAL


class TestHealthStatusResetMethods:
    """Tests for HealthStatus reset methods."""

    def test_reset_stuck_threads(self) -> None:
        """reset_stuck_threads should clear stuck_threads counter."""
        status = HealthStatus()
        status.stuck_threads = 5
        status._evaluate_state()
        assert status.state == HealthState.CRITICAL

        status.reset_stuck_threads()

        assert status.stuck_threads == 0
        assert status.state == HealthState.HEALTHY

    def test_reset_pool_exhaustions(self) -> None:
        """reset_pool_exhaustions should clear pool_exhaustions counter."""
        status = HealthStatus()
        status.pool_exhaustions = 10
        status._evaluate_state()
        assert status.state == HealthState.CRITICAL

        status.reset_pool_exhaustions()

        assert status.pool_exhaustions == 0
        assert status.state == HealthState.HEALTHY

    def test_reset_clears_all_counters(self) -> None:
        """reset should clear all counters and state."""
        status = HealthStatus()
        status.consecutive_failures = 15
        status.stuck_threads = 5
        status.pool_exhaustions = 10
        status.state = HealthState.CRITICAL

        status.reset()

        assert status.state == HealthState.HEALTHY
        assert status.consecutive_failures == 0
        assert status.stuck_threads == 0
        assert status.pool_exhaustions == 0

    def test_reset_keeps_totals(self) -> None:
        """reset should preserve total counters."""
        status = HealthStatus()
        status.total_successes = 100
        status.total_failures = 50

        status.reset()

        assert status.total_successes == 100
        assert status.total_failures == 50


class TestHealthStatusStateProperties:
    """Tests for HealthStatus state property methods."""

    def test_is_healthy_when_healthy(self) -> None:
        """is_healthy should return True when HEALTHY."""
        status = HealthStatus()
        assert status.is_healthy is True

    def test_is_healthy_when_not_healthy(self) -> None:
        """is_healthy should return False when not HEALTHY."""
        status = HealthStatus()
        status.state = HealthState.DEGRADED
        assert status.is_healthy is False

    def test_is_degraded_when_degraded(self) -> None:
        """is_degraded should return True when DEGRADED."""
        status = HealthStatus()
        status.state = HealthState.DEGRADED
        assert status.is_degraded is True

    def test_is_degraded_when_not_degraded(self) -> None:
        """is_degraded should return False when not DEGRADED."""
        status = HealthStatus()
        assert status.is_degraded is False

    def test_is_critical_when_critical(self) -> None:
        """is_critical should return True when CRITICAL."""
        status = HealthStatus()
        status.state = HealthState.CRITICAL
        assert status.is_critical is True

    def test_is_critical_when_not_critical(self) -> None:
        """is_critical should return False when not CRITICAL."""
        status = HealthStatus()
        assert status.is_critical is False


class TestHealthStatusToDict:
    """Tests for HealthStatus.to_dict method."""

    def test_to_dict_includes_all_fields(self) -> None:
        """to_dict should include all status fields."""
        status = HealthStatus()
        status.record_success()
        status.record_failure()

        result = status.to_dict()

        assert "state" in result
        assert "last_success" in result
        assert "consecutive_failures" in result
        assert "stuck_threads" in result
        assert "pool_exhaustions" in result
        assert "total_successes" in result
        assert "total_failures" in result

    def test_to_dict_state_is_string(self) -> None:
        """to_dict should export state as string name."""
        status = HealthStatus()
        result = status.to_dict()
        assert result["state"] == "HEALTHY"

        status.state = HealthState.DEGRADED
        result = status.to_dict()
        assert result["state"] == "DEGRADED"

    def test_to_dict_last_success_format(self) -> None:
        """to_dict should export last_success as ISO format string."""
        status = HealthStatus()
        result = status.to_dict()
        assert result["last_success"] is None

        status.record_success()
        result = status.to_dict()
        assert result["last_success"] is not None
        assert "T" in result["last_success"]  # ISO format contains T


class TestHealthStatusStatePriority:
    """Tests for state priority logic."""

    def test_critical_takes_priority_over_degraded(self) -> None:
        """CRITICAL should take priority over DEGRADED conditions."""
        status = HealthStatus()

        # Set both degraded and critical conditions
        status.consecutive_failures = 15  # Would cause DEGRADED
        status.stuck_threads = 5  # Would cause CRITICAL

        status._evaluate_state()

        assert status.state == HealthState.CRITICAL

    def test_stuck_threads_critical_independent_of_failures(self) -> None:
        """stuck_threads should trigger CRITICAL regardless of failures."""
        status = HealthStatus()
        status.consecutive_failures = 0

        for _ in range(3):
            status.record_stuck_thread()

        assert status.state == HealthState.CRITICAL

    def test_pool_exhaustion_critical_independent_of_failures(self) -> None:
        """pool_exhaustions should trigger CRITICAL regardless of failures."""
        status = HealthStatus()
        status.consecutive_failures = 0

        for _ in range(5):
            status.record_pool_exhaustion()

        assert status.state == HealthState.CRITICAL


class TestHealthStatusThreadSafety:
    """Tests for thread safety of HealthStatus."""

    def test_concurrent_record_success(self) -> None:
        """Concurrent record_success calls should be safe."""
        status = HealthStatus()

        def record_many():
            for _ in range(1000):
                status.record_success()

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(record_many) for _ in range(4)]
            for f in futures:
                f.result()

        assert status.total_successes == 4000

    def test_concurrent_record_failure(self) -> None:
        """Concurrent record_failure calls should be safe."""
        status = HealthStatus()

        def record_many():
            for _ in range(1000):
                status.record_failure()

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(record_many) for _ in range(4)]
            for f in futures:
                f.result()

        assert status.total_failures == 4000

    def test_concurrent_mixed_operations(self) -> None:
        """Mixed concurrent operations should be safe."""
        status = HealthStatus()
        barrier = threading.Barrier(3)

        def do_successes():
            barrier.wait()
            for _ in range(500):
                status.record_success()

        def do_failures():
            barrier.wait()
            for _ in range(500):
                status.record_failure()

        def do_reads():
            barrier.wait()
            for _ in range(500):
                _ = status.to_dict()
                _ = status.is_healthy

        with ThreadPoolExecutor(max_workers=3) as executor:
            f1 = executor.submit(do_successes)
            f2 = executor.submit(do_failures)
            f3 = executor.submit(do_reads)

            f1.result()
            f2.result()
            f3.result()

        assert status.total_successes == 500
        assert status.total_failures == 500
