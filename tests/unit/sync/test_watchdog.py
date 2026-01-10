"""Unit tests for commandbus.sync.watchdog module."""

import time
from unittest.mock import MagicMock, patch

from commandbus.sync.health import HealthState, HealthStatus
from commandbus.sync.process.router import SyncProcessReplyRouter
from commandbus.sync.watchdog import WorkerWatchdog
from commandbus.sync.worker import SyncWorker


class MockWatchable:
    """Mock worker that implements Watchable protocol."""

    def __init__(self) -> None:
        self._health = HealthStatus()
        self.stop_called = False
        self.stop_timeout: float | None = None

    @property
    def health_status(self) -> HealthStatus:
        return self._health

    def stop(self, timeout: float | None = None) -> None:
        self.stop_called = True
        self.stop_timeout = timeout


class TestWatchableProtocol:
    """Tests for Watchable protocol."""

    def test_mock_worker_satisfies_protocol(self) -> None:
        """MockWatchable should satisfy Watchable protocol."""
        worker = MockWatchable()
        # Protocol check - if this doesn't error, it satisfies the protocol
        assert hasattr(worker, "health_status")
        assert hasattr(worker, "stop")
        assert isinstance(worker.health_status, HealthStatus)


class TestWorkerWatchdogInit:
    """Tests for WorkerWatchdog initialization."""

    def test_init_with_required_args(self) -> None:
        """Should initialize with required arguments."""
        worker = MockWatchable()

        watchdog = WorkerWatchdog(worker)

        assert watchdog._worker is worker
        assert watchdog._check_interval == 10.0
        assert watchdog._restart_callback is None
        assert watchdog._name == "worker-watchdog"

    def test_init_with_custom_interval(self) -> None:
        """Should allow custom check interval."""
        worker = MockWatchable()

        watchdog = WorkerWatchdog(worker, check_interval=5.0)

        assert watchdog._check_interval == 5.0

    def test_init_with_restart_callback(self) -> None:
        """Should store restart callback."""
        worker = MockWatchable()
        callback = MagicMock()

        watchdog = WorkerWatchdog(worker, restart_callback=callback)

        assert watchdog._restart_callback is callback

    def test_init_with_custom_name(self) -> None:
        """Should allow custom watchdog name."""
        worker = MockWatchable()

        watchdog = WorkerWatchdog(worker, name="my-watchdog")

        assert watchdog._name == "my-watchdog"


class TestWorkerWatchdogProperties:
    """Tests for WorkerWatchdog properties."""

    def test_is_running_false_initially(self) -> None:
        """Should return False when not started."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker)

        assert watchdog.is_running is False

    def test_recovery_triggered_false_initially(self) -> None:
        """Should return False when no recovery triggered."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker)

        assert watchdog.recovery_triggered is False


class TestWorkerWatchdogStart:
    """Tests for WorkerWatchdog.start method."""

    def test_start_creates_daemon_thread(self) -> None:
        """Should create a daemon thread when started."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker, check_interval=0.1)

        watchdog.start()
        try:
            assert watchdog.is_running is True
            assert watchdog._thread is not None
            assert watchdog._thread.daemon is True
            assert watchdog._thread.name == "worker-watchdog"
        finally:
            watchdog.stop()

    def test_start_with_custom_name(self) -> None:
        """Should use custom name for thread."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker, check_interval=0.1, name="my-watchdog")

        watchdog.start()
        try:
            assert watchdog._thread is not None
            assert watchdog._thread.name == "my-watchdog"
        finally:
            watchdog.stop()

    def test_start_resets_recovery_triggered(self) -> None:
        """Should reset recovery_triggered on start."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker, check_interval=0.1)
        watchdog._recovery_triggered = True

        watchdog.start()
        try:
            assert watchdog.recovery_triggered is False
        finally:
            watchdog.stop()

    def test_start_when_already_running_warns(self) -> None:
        """Should warn if already running."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker, check_interval=0.1)

        watchdog.start()
        try:
            with patch("commandbus.sync.watchdog.logger") as mock_logger:
                watchdog.start()
                mock_logger.warning.assert_called_once()
        finally:
            watchdog.stop()


class TestWorkerWatchdogStop:
    """Tests for WorkerWatchdog.stop method."""

    def test_stop_sets_event(self) -> None:
        """Should set stop event."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker, check_interval=0.1)
        watchdog.start()

        watchdog.stop()

        assert watchdog._stop_event.is_set()
        assert watchdog.is_running is False

    def test_stop_when_not_running(self) -> None:
        """Should handle stop when not running."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker)

        # Should not raise
        watchdog.stop()

    def test_stop_waits_for_thread(self) -> None:
        """Should wait for thread to exit."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker, check_interval=0.1)
        watchdog.start()

        watchdog.stop(timeout=5.0)

        assert watchdog._thread is None


class TestWorkerWatchdogHealthCheck:
    """Tests for WorkerWatchdog._check_health method."""

    def test_check_health_healthy_state(self) -> None:
        """Should log debug for healthy state."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker)

        with patch("commandbus.sync.watchdog.logger") as mock_logger:
            watchdog._check_health()

        mock_logger.debug.assert_called_once()
        assert "HEALTHY" in mock_logger.debug.call_args[0][0]

    def test_check_health_degraded_state(self) -> None:
        """Should log warning for degraded state."""
        worker = MockWatchable()
        # Trigger degraded state
        for _ in range(10):
            worker._health.record_failure()
        assert worker.health_status.state == HealthState.DEGRADED

        watchdog = WorkerWatchdog(worker)

        with patch("commandbus.sync.watchdog.logger") as mock_logger:
            watchdog._check_health()

        mock_logger.warning.assert_called()
        assert "DEGRADED" in mock_logger.warning.call_args[0][0]
        assert worker.stop_called is False  # Should not stop for degraded

    def test_check_health_critical_state_triggers_recovery(self) -> None:
        """Should trigger recovery for critical state."""
        worker = MockWatchable()
        # Trigger critical state
        for _ in range(3):
            worker._health.record_stuck_thread()
        assert worker.health_status.state == HealthState.CRITICAL

        watchdog = WorkerWatchdog(worker)

        with patch("commandbus.sync.watchdog.logger"):
            watchdog._check_health()

        assert watchdog.recovery_triggered is True
        assert worker.stop_called is True


class TestWorkerWatchdogTriggerRecovery:
    """Tests for WorkerWatchdog._trigger_recovery method."""

    def test_trigger_recovery_calls_worker_stop(self) -> None:
        """Should call worker.stop() when no callback."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker)

        watchdog._trigger_recovery()

        assert watchdog.recovery_triggered is True
        assert worker.stop_called is True

    def test_trigger_recovery_calls_callback(self) -> None:
        """Should call restart callback if provided."""
        worker = MockWatchable()
        callback = MagicMock()
        watchdog = WorkerWatchdog(worker, restart_callback=callback)

        watchdog._trigger_recovery()

        assert watchdog.recovery_triggered is True
        callback.assert_called_once()
        assert worker.stop_called is False  # Worker not stopped, callback handles it

    def test_trigger_recovery_only_once(self) -> None:
        """Should only trigger recovery once."""
        worker = MockWatchable()
        callback = MagicMock()
        watchdog = WorkerWatchdog(worker, restart_callback=callback)

        watchdog._trigger_recovery()
        watchdog._trigger_recovery()

        callback.assert_called_once()

    def test_trigger_recovery_handles_callback_error(self) -> None:
        """Should log error if callback fails."""
        worker = MockWatchable()
        callback = MagicMock(side_effect=Exception("Callback error"))
        watchdog = WorkerWatchdog(worker, restart_callback=callback)

        with patch("commandbus.sync.watchdog.logger") as mock_logger:
            watchdog._trigger_recovery()

        mock_logger.exception.assert_called()
        assert "restart callback" in mock_logger.exception.call_args[0][0]

    def test_trigger_recovery_handles_stop_error(self) -> None:
        """Should log error if worker.stop() fails."""
        worker = MockWatchable()
        worker.stop = MagicMock(side_effect=Exception("Stop error"))  # type: ignore[method-assign]
        watchdog = WorkerWatchdog(worker)

        with patch("commandbus.sync.watchdog.logger") as mock_logger:
            watchdog._trigger_recovery()

        mock_logger.exception.assert_called()
        assert "stopping worker" in mock_logger.exception.call_args[0][0]


class TestWorkerWatchdogMonitorLoop:
    """Tests for WorkerWatchdog._monitor_loop method."""

    def test_monitor_loop_checks_health_periodically(self) -> None:
        """Should check health at specified interval."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker, check_interval=0.05)

        check_count = 0
        original_check = watchdog._check_health

        def counting_check() -> None:
            nonlocal check_count
            check_count += 1
            original_check()

        watchdog._check_health = counting_check  # type: ignore[method-assign]

        watchdog.start()
        time.sleep(0.2)
        watchdog.stop()

        # Should have checked multiple times
        assert check_count >= 2

    def test_monitor_loop_handles_check_error(self) -> None:
        """Should log error and continue on check failure."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker, check_interval=0.05)

        call_count = 0

        def failing_check() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Check error")

        watchdog._check_health = failing_check  # type: ignore[method-assign]

        with patch("commandbus.sync.watchdog.logger") as mock_logger:
            watchdog.start()
            time.sleep(0.15)
            watchdog.stop()

        # Should have logged exception
        mock_logger.exception.assert_called()
        # Should have continued checking
        assert call_count >= 2


class TestWorkerWatchdogIntegration:
    """Integration tests for WorkerWatchdog with real workers."""

    def test_watchdog_monitors_real_sync_worker(self) -> None:
        """Should work with SyncWorker health_status."""
        mock_pool = MagicMock()
        worker = SyncWorker(pool=mock_pool, domain="test")

        watchdog = WorkerWatchdog(worker, check_interval=0.05)
        watchdog.start()
        try:
            time.sleep(0.1)
            assert watchdog.is_running is True
        finally:
            watchdog.stop()

    def test_watchdog_monitors_real_sync_router(self) -> None:
        """Should work with SyncProcessReplyRouter health_status."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()
        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="test__replies",
            domain="test",
        )

        watchdog = WorkerWatchdog(router, check_interval=0.05)
        watchdog.start()
        try:
            time.sleep(0.1)
            assert watchdog.is_running is True
        finally:
            watchdog.stop()

    def test_watchdog_detects_critical_state_and_stops_worker(self) -> None:
        """Should detect critical state and stop worker."""
        worker = MockWatchable()
        watchdog = WorkerWatchdog(worker, check_interval=0.05)

        watchdog.start()
        time.sleep(0.02)  # Let watchdog start

        # Trigger critical state
        for _ in range(3):
            worker._health.record_stuck_thread()

        # Wait for watchdog to detect
        time.sleep(0.1)

        watchdog.stop()

        assert watchdog.recovery_triggered is True
        assert worker.stop_called is True
