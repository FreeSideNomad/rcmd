"""Unit tests for commandbus.sync.process.router module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from commandbus.models import Reply, ReplyOutcome
from commandbus.process.models import ProcessMetadata, ProcessStatus
from commandbus.sync.health import HealthState
from commandbus.sync.process.router import SyncProcessManager, SyncProcessReplyRouter


class TestSyncProcessManager:
    """Tests for SyncProcessManager protocol."""

    def test_protocol_defines_handle_reply_sync(self) -> None:
        """Should define handle_reply_sync method."""
        assert hasattr(SyncProcessManager, "handle_reply_sync")


class TestSyncProcessReplyRouterInit:
    """Tests for SyncProcessReplyRouter initialization."""

    def test_init_with_required_args(self) -> None:
        """Should initialize with required arguments."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()
        managers: dict[str, SyncProcessManager] = {}

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers=managers,
            reply_queue="orders__replies",
            domain="orders",
        )

        assert router._pool is mock_pool
        assert router._process_repo is mock_process_repo
        assert router._managers is managers
        assert router._reply_queue == "orders__replies"
        assert router._domain == "orders"
        assert router._visibility_timeout == 30
        assert router._statement_timeout == 25000

    def test_init_with_custom_timeouts(self) -> None:
        """Should allow custom visibility and statement timeouts."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
            visibility_timeout=60,
            statement_timeout=30000,
        )

        assert router._visibility_timeout == 60
        assert router._statement_timeout == 30000


class TestSyncProcessReplyRouterProperties:
    """Tests for SyncProcessReplyRouter properties."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.mock_process_repo = MagicMock()
        self.router = SyncProcessReplyRouter(
            pool=self.mock_pool,
            process_repo=self.mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
        )

    def test_reply_queue_property(self) -> None:
        """Should return the reply queue name."""
        assert self.router.reply_queue == "orders__replies"

    def test_domain_property(self) -> None:
        """Should return the domain."""
        assert self.router.domain == "orders"

    def test_health_status_property(self) -> None:
        """Should return the health status tracker."""
        assert self.router.health_status is self.router._health
        assert self.router.health_status.state == HealthState.HEALTHY

    def test_is_running_false_initially(self) -> None:
        """Should return False when not running."""
        assert self.router.is_running is False

    def test_in_flight_count_zero_initially(self) -> None:
        """Should return 0 when nothing in flight."""
        assert self.router.in_flight_count == 0


class TestSyncProcessReplyRouterRun:
    """Tests for SyncProcessReplyRouter.run method."""

    def test_run_creates_thread_pool(self) -> None:
        """Should create ThreadPoolExecutor with specified concurrency."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
        )

        # Patch _run_loop to avoid blocking
        with patch.object(router, "_run_loop"):
            router.run(concurrency=8, poll_interval=0.1)

        assert router._concurrency == 8


class TestSyncProcessReplyRouterStop:
    """Tests for SyncProcessReplyRouter.stop method."""

    def test_stop_sets_event(self) -> None:
        """Should set the stop event."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
        )

        assert not router._stop_event.is_set()

        router.stop()

        assert router._stop_event.is_set()

    def test_stop_waits_for_in_flight(self) -> None:
        """Should wait for in-flight replies when stopping."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
        )

        # Simulate in-flight work
        mock_future = MagicMock()
        mock_future.done.return_value = True
        router._in_flight[1] = (mock_future, 0.0)

        with patch.object(router, "_drain_in_flight") as mock_drain:
            router.stop(timeout=10.0)

        mock_drain.assert_called_once_with(timeout=10.0)


class TestSyncProcessReplyRouterDispatchReply:
    """Tests for SyncProcessReplyRouter._dispatch_reply method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.mock_conn = MagicMock()
        self.mock_process_repo = MagicMock()
        self.mock_manager = MagicMock(spec=SyncProcessManager)

        # Setup connection context managers
        self.mock_pool.connection.return_value.__enter__ = MagicMock(return_value=self.mock_conn)
        self.mock_pool.connection.return_value.__exit__ = MagicMock(return_value=None)
        self.mock_conn.transaction.return_value.__enter__ = MagicMock()
        self.mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=None)

        self.router = SyncProcessReplyRouter(
            pool=self.mock_pool,
            process_repo=self.mock_process_repo,
            managers={"OrderProcess": self.mock_manager},
            reply_queue="orders__replies",
            domain="orders",
        )
        self.router._pgmq = MagicMock()

    def test_dispatch_reply_no_correlation_id_discards(self) -> None:
        """Should discard reply if no correlation_id."""
        msg = MagicMock()
        msg.msg_id = 1
        msg.message = {
            "command_id": str(uuid4()),
            "correlation_id": None,
            "outcome": "SUCCESS",
        }

        self.router._dispatch_reply(msg)

        self.router._pgmq.delete.assert_called_once()
        self.mock_manager.handle_reply_sync.assert_not_called()

    def test_dispatch_reply_unknown_process_discards(self) -> None:
        """Should discard reply if process not found."""
        process_id = uuid4()
        msg = MagicMock()
        msg.msg_id = 1
        msg.message = {
            "command_id": str(uuid4()),
            "correlation_id": str(process_id),
            "outcome": "SUCCESS",
        }

        self.mock_process_repo.get_by_id = MagicMock(return_value=None)

        self.router._dispatch_reply(msg)

        self.router._pgmq.delete.assert_called_once()
        self.mock_manager.handle_reply_sync.assert_not_called()

    def test_dispatch_reply_unknown_manager_discards(self) -> None:
        """Should discard reply if no manager for process type."""
        process_id = uuid4()
        msg = MagicMock()
        msg.msg_id = 1
        msg.message = {
            "command_id": str(uuid4()),
            "correlation_id": str(process_id),
            "outcome": "SUCCESS",
        }

        # Return a process with unknown type
        process = ProcessMetadata(
            domain="orders",
            process_id=process_id,
            process_type="UnknownProcess",
            status=ProcessStatus.WAITING_FOR_REPLY,
            current_step="step1",
            state={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.mock_process_repo.get_by_id = MagicMock(return_value=process)

        self.router._dispatch_reply(msg)

        self.router._pgmq.delete.assert_called_once()
        self.mock_manager.handle_reply_sync.assert_not_called()

    def test_dispatch_reply_success(self) -> None:
        """Should dispatch reply to manager and delete message."""
        process_id = uuid4()
        command_id = uuid4()
        msg = MagicMock()
        msg.msg_id = 1
        msg.message = {
            "command_id": str(command_id),
            "correlation_id": str(process_id),
            "outcome": "SUCCESS",
            "result": {"status": "ok"},
        }

        process = ProcessMetadata(
            domain="orders",
            process_id=process_id,
            process_type="OrderProcess",
            status=ProcessStatus.WAITING_FOR_REPLY,
            current_step="step1",
            state={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.mock_process_repo.get_by_id = MagicMock(return_value=process)

        self.router._dispatch_reply(msg)

        # Verify manager was called
        self.mock_manager.handle_reply_sync.assert_called_once()
        call_args = self.mock_manager.handle_reply_sync.call_args
        reply = call_args[0][0]
        assert isinstance(reply, Reply)
        assert reply.command_id == command_id
        assert reply.correlation_id == process_id
        assert reply.outcome == ReplyOutcome.SUCCESS

        # Verify message was deleted
        self.router._pgmq.delete.assert_called_once()


class TestSyncProcessReplyRouterProcessReply:
    """Tests for SyncProcessReplyRouter._process_reply method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.mock_conn = MagicMock()
        self.mock_process_repo = MagicMock()

        # Setup connection context managers
        self.mock_pool.connection.return_value.__enter__ = MagicMock(return_value=self.mock_conn)
        self.mock_pool.connection.return_value.__exit__ = MagicMock(return_value=None)
        self.mock_conn.transaction.return_value.__enter__ = MagicMock()
        self.mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=None)

        self.router = SyncProcessReplyRouter(
            pool=self.mock_pool,
            process_repo=self.mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
        )

    def test_process_reply_success_updates_health(self) -> None:
        """Should record success on successful processing."""
        msg = MagicMock()
        msg.msg_id = 1

        with patch.object(self.router, "_dispatch_reply"):
            self.router._process_reply(msg)

        assert self.router._health.state == HealthState.HEALTHY

    def test_process_reply_error_updates_health(self) -> None:
        """Should record failure on processing error."""
        msg = MagicMock()
        msg.msg_id = 1

        with patch.object(self.router, "_dispatch_reply", side_effect=Exception("Test error")):
            self.router._process_reply(msg)

        # Health should record the failure
        assert self.router._health.consecutive_failures >= 1

    def test_process_reply_removes_from_in_flight(self) -> None:
        """Should remove from in-flight tracking on completion."""
        msg = MagicMock()
        msg.msg_id = 42

        # Add to in-flight
        self.router._in_flight[42] = (MagicMock(), 0.0)

        with patch.object(self.router, "_dispatch_reply"):
            self.router._process_reply(msg)

        assert 42 not in self.router._in_flight


class TestSyncProcessReplyRouterHealthTracking:
    """Tests for health status tracking in SyncProcessReplyRouter."""

    def test_check_stuck_threads(self) -> None:
        """Should detect stuck threads based on timeout."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
            visibility_timeout=1,
        )

        # Add an old in-flight task
        mock_future = MagicMock()
        mock_future.done.return_value = False
        router._in_flight[1] = (mock_future, 0.0)

        # Check with current time way past threshold
        with patch("commandbus.sync.process.router.time.monotonic", return_value=100.0):
            router._check_stuck_threads()

        assert router._health.stuck_threads == 1

    def test_cleanup_completed_removes_done_futures(self) -> None:
        """Should remove completed futures from in-flight."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
        )

        # Add a completed future
        done_future = MagicMock()
        done_future.done.return_value = True
        router._in_flight[1] = (done_future, 0.0)

        # Add a not-done future
        pending_future = MagicMock()
        pending_future.done.return_value = False
        router._in_flight[2] = (pending_future, 0.0)

        router._cleanup_completed()

        assert 1 not in router._in_flight
        assert 2 in router._in_flight


class TestSyncProcessReplyRouterDrain:
    """Tests for SyncProcessReplyRouter._drain_in_flight method."""

    def test_drain_empty_returns_immediately(self) -> None:
        """Should return immediately when no in-flight tasks."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
        )

        # Should not raise and return quickly
        router._drain_in_flight(timeout=1.0)

    def test_drain_waits_for_futures(self) -> None:
        """Should wait for all futures to complete."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
        )

        mock_future = MagicMock()
        router._in_flight[1] = (mock_future, 0.0)

        with patch("commandbus.sync.process.router.wait") as mock_wait:
            mock_wait.return_value = ({mock_future}, set())
            router._drain_in_flight(timeout=5.0)

        mock_wait.assert_called_once()


class TestSyncProcessReplyRouterWaitForSlot:
    """Tests for SyncProcessReplyRouter._wait_for_slot method."""

    def test_wait_for_slot_empty_returns(self) -> None:
        """Should return immediately when no in-flight tasks."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
        )

        # Should not block
        router._wait_for_slot(timeout=0.1)

    def test_wait_for_slot_waits_for_completion(self) -> None:
        """Should wait for any task to complete."""
        mock_pool = MagicMock()
        mock_process_repo = MagicMock()

        router = SyncProcessReplyRouter(
            pool=mock_pool,
            process_repo=mock_process_repo,
            managers={},
            reply_queue="orders__replies",
            domain="orders",
        )

        mock_future = MagicMock()
        router._in_flight[1] = (mock_future, 0.0)

        with patch("commandbus.sync.process.router.wait") as mock_wait:
            mock_wait.return_value = ({mock_future}, set())
            router._wait_for_slot(timeout=1.0)

        mock_wait.assert_called_once()
        _args, kwargs = mock_wait.call_args
        assert kwargs.get("return_when") == "FIRST_COMPLETED"
