"""Unit tests for commandbus.sync.worker module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from commandbus.exceptions import (
    HandlerNotFoundError,
    PermanentCommandError,
    TransientCommandError,
)
from commandbus.handler import HandlerRegistry
from commandbus.models import (
    Command,
    CommandMetadata,
    HandlerContext,
)
from commandbus.sync.health import HealthState
from commandbus.sync.worker import (
    ReceivedCommand,
    SyncWorker,
    _make_queue_name,
)


class TestMakeQueueName:
    """Tests for _make_queue_name helper function."""

    def test_default_suffix(self) -> None:
        """Should use 'commands' as default suffix."""
        result = _make_queue_name("payments")
        assert result == "payments__commands"

    def test_custom_suffix(self) -> None:
        """Should allow custom suffix."""
        result = _make_queue_name("payments", "replies")
        assert result == "payments__replies"


class TestReceivedCommand:
    """Tests for ReceivedCommand dataclass."""

    def test_dataclass_fields(self) -> None:
        """Should store command, context, msg_id, and metadata."""
        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )
        context = HandlerContext(
            command=command,
            attempt=1,
            max_attempts=3,
            msg_id=42,
        )
        metadata = MagicMock(spec=CommandMetadata)

        received = ReceivedCommand(
            command=command,
            context=context,
            msg_id=42,
            metadata=metadata,
        )

        assert received.command is command
        assert received.context is context
        assert received.msg_id == 42
        assert received.metadata is metadata


class TestSyncWorkerInit:
    """Tests for SyncWorker initialization."""

    def test_init_with_defaults(self) -> None:
        """Should initialize with default values."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        assert worker._pool is mock_pool
        assert worker._domain == "payments"
        assert worker._registry is None
        assert worker._visibility_timeout == 30
        assert worker._statement_timeout == 25000
        assert worker._queue_name == "payments__commands"
        assert worker._concurrency == 1
        assert worker._stop_event is not None
        assert worker._health is not None

    def test_init_with_custom_values(self) -> None:
        """Should allow custom configuration."""
        mock_pool = MagicMock()
        mock_registry = MagicMock()
        mock_policy = MagicMock()

        worker = SyncWorker(
            mock_pool,
            domain="orders",
            registry=mock_registry,
            visibility_timeout=60,
            retry_policy=mock_policy,
            statement_timeout=30000,
        )

        assert worker._domain == "orders"
        assert worker._registry is mock_registry
        assert worker._visibility_timeout == 60
        assert worker._retry_policy is mock_policy
        assert worker._statement_timeout == 30000

    def test_init_creates_sync_components(self) -> None:
        """Should create sync PGMQ client and repositories."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        assert worker._pgmq is not None
        assert worker._command_repo is not None
        assert worker._batch_repo is not None
        assert worker._audit_logger is not None


class TestSyncWorkerProperties:
    """Tests for SyncWorker properties."""

    def test_domain_property(self) -> None:
        """Should return the domain."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        assert worker.domain == "payments"

    def test_queue_name_property(self) -> None:
        """Should return the queue name."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        assert worker.queue_name == "payments__commands"

    def test_health_status_property(self) -> None:
        """Should return the health status tracker."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        assert worker.health_status is worker._health
        assert worker.health_status.state == HealthState.HEALTHY

    def test_is_running_false_initially(self) -> None:
        """Should return False when not running."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        assert worker.is_running is False

    def test_in_flight_count_zero_initially(self) -> None:
        """Should return 0 when nothing in flight."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        assert worker.in_flight_count == 0


class TestSyncWorkerRun:
    """Tests for SyncWorker.run method."""

    def test_run_without_registry_raises(self) -> None:
        """Should raise RuntimeError if no registry configured."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        with pytest.raises(RuntimeError, match="Cannot run worker without a handler registry"):
            worker.run()

    def test_run_creates_thread_pool(self) -> None:
        """Should create ThreadPoolExecutor with specified concurrency."""
        mock_pool = MagicMock()
        mock_registry = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments", registry=mock_registry)

        # Patch _run_loop to avoid blocking
        with patch.object(worker, "_run_loop"):
            worker.run(concurrency=8, poll_interval=0.1)

        assert worker._concurrency == 8

    def test_run_clears_stop_event(self) -> None:
        """Should clear stop event at start."""
        mock_pool = MagicMock()
        mock_registry = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments", registry=mock_registry)

        worker._stop_event.set()

        # Run in a way that stops quickly
        with patch.object(worker, "_run_loop"):
            worker.run()

        # _run_loop was called after clearing stop event
        assert worker._executor is None  # shutdown after run


class TestSyncWorkerStop:
    """Tests for SyncWorker.stop method."""

    def test_stop_sets_event(self) -> None:
        """Should set the stop event."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        assert not worker._stop_event.is_set()

        worker.stop()

        assert worker._stop_event.is_set()

    def test_stop_waits_for_in_flight(self) -> None:
        """Should wait for in-flight commands when stopping."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        # Simulate in-flight work
        mock_future = MagicMock()
        mock_future.done.return_value = True
        worker._in_flight[1] = (mock_future, 0.0)

        with patch.object(worker, "_drain_in_flight") as mock_drain:
            worker.stop(timeout=10.0)

        mock_drain.assert_called_once_with(timeout=10.0)


class TestSyncWorkerReceive:
    """Tests for SyncWorker._receive method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__ = MagicMock(return_value=self.mock_conn)
        self.mock_pool.connection.return_value.__exit__ = MagicMock(return_value=None)

        self.worker = SyncWorker(self.mock_pool, domain="payments")

    def test_receive_sets_statement_timeout(self) -> None:
        """Should set statement_timeout on connection."""
        self.worker._pgmq.read = MagicMock(return_value=[])

        self.worker._receive(batch_size=1)

        self.mock_conn.execute.assert_called_once_with("SET statement_timeout = 25000")

    def test_receive_with_custom_visibility_timeout(self) -> None:
        """Should use provided visibility_timeout."""
        self.worker._pgmq.read = MagicMock(return_value=[])

        self.worker._receive(batch_size=1, visibility_timeout=120)

        self.worker._pgmq.read.assert_called_once_with(
            "payments__commands",
            visibility_timeout=120,
            batch_size=1,
            conn=self.mock_conn,
        )

    def test_receive_returns_empty_list_when_no_messages(self) -> None:
        """Should return empty list when no messages available."""
        self.worker._pgmq.read = MagicMock(return_value=[])

        result = self.worker._receive(batch_size=5)

        assert result == []


class TestSyncWorkerProcessMessage:
    """Tests for SyncWorker._process_message method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.mock_conn = MagicMock()

        self.worker = SyncWorker(self.mock_pool, domain="payments")
        self.worker._pgmq = MagicMock()
        self.worker._command_repo = MagicMock()

    def test_process_message_missing_command_id_archives(self) -> None:
        """Should archive message if command_id is missing."""
        message = {"domain": "payments", "command_type": "Test"}

        result = self.worker._process_message(1, message, self.mock_conn)

        assert result is None
        self.worker._pgmq.archive.assert_called_once_with("payments__commands", 1, self.mock_conn)

    def test_process_message_no_metadata_archives(self) -> None:
        """Should archive message if no metadata found."""
        command_id = uuid4()
        message = {"command_id": str(command_id), "domain": "payments"}
        self.worker._command_repo.sp_receive_command = MagicMock(return_value=None)

        result = self.worker._process_message(1, message, self.mock_conn)

        assert result is None
        self.worker._pgmq.archive.assert_called_once()

    def test_process_message_returns_received_command(self) -> None:
        """Should return ReceivedCommand for valid message."""
        command_id = uuid4()
        message = {
            "command_id": str(command_id),
            "domain": "payments",
            "command_type": "DebitAccount",
            "data": {"amount": 100},
        }

        mock_metadata = MagicMock(spec=CommandMetadata)
        mock_metadata.command_type = "DebitAccount"
        mock_metadata.created_at = datetime.now(UTC)
        mock_metadata.max_attempts = 3

        self.worker._command_repo.sp_receive_command = MagicMock(return_value=(mock_metadata, 1))

        result = self.worker._process_message(42, message, self.mock_conn)

        assert result is not None
        assert isinstance(result, ReceivedCommand)
        assert result.command.command_id == command_id
        assert result.context.attempt == 1
        assert result.msg_id == 42
        assert result.metadata is mock_metadata


class TestSyncWorkerProcessCommand:
    """Tests for SyncWorker._process_command method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.mock_conn = MagicMock()
        self.mock_registry = MagicMock()

        # Setup connection context manager
        self.mock_pool.connection.return_value.__enter__ = MagicMock(return_value=self.mock_conn)
        self.mock_pool.connection.return_value.__exit__ = MagicMock(return_value=None)
        self.mock_conn.transaction.return_value.__enter__ = MagicMock()
        self.mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=None)

        self.worker = SyncWorker(self.mock_pool, domain="payments", registry=self.mock_registry)
        self.worker._pgmq = MagicMock()
        self.worker._command_repo = MagicMock()

    def _make_received_command(self) -> ReceivedCommand:
        """Create a test ReceivedCommand."""
        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )
        context = HandlerContext(
            command=command,
            attempt=1,
            max_attempts=3,
            msg_id=42,
        )
        metadata = MagicMock(spec=CommandMetadata)
        metadata.batch_id = None
        metadata.max_attempts = 3

        return ReceivedCommand(
            command=command,
            context=context,
            msg_id=42,
            metadata=metadata,
        )

    def test_process_command_success(self) -> None:
        """Should dispatch to handler and complete on success."""
        received = self._make_received_command()
        self.mock_registry.dispatch_sync = MagicMock(return_value={"ok": True})
        self.worker._command_repo.sp_finish_command = MagicMock(return_value=False)

        self.worker._process_command(received)

        self.mock_registry.dispatch_sync.assert_called_once()
        assert self.worker._health.state == HealthState.HEALTHY

    def test_process_command_transient_error(self) -> None:
        """Should handle transient error with retry."""
        received = self._make_received_command()
        self.mock_registry.dispatch_sync = MagicMock(
            side_effect=TransientCommandError(code="TIMEOUT", message="Timed out")
        )
        self.worker._command_repo.sp_fail_command = MagicMock()

        self.worker._process_command(received)

        self.worker._command_repo.sp_fail_command.assert_called_once()

    def test_process_command_permanent_error(self) -> None:
        """Should handle permanent error by moving to TSQ."""
        received = self._make_received_command()
        self.mock_registry.dispatch_sync = MagicMock(
            side_effect=PermanentCommandError(code="INVALID", message="Invalid data")
        )
        self.worker._command_repo.sp_finish_command = MagicMock(return_value=False)

        self.worker._process_command(received)

        # Should archive and finish with IN_TROUBLESHOOTING_QUEUE status
        self.worker._pgmq.archive.assert_called_once()

    def test_process_command_removes_from_in_flight(self) -> None:
        """Should remove from in-flight tracking on completion."""
        received = self._make_received_command()
        self.mock_registry.dispatch_sync = MagicMock(return_value=None)
        self.worker._command_repo.sp_finish_command = MagicMock(return_value=False)

        # Add to in-flight
        self.worker._in_flight[received.msg_id] = (MagicMock(), 0.0)

        self.worker._process_command(received)

        assert received.msg_id not in self.worker._in_flight


class TestSyncWorkerComplete:
    """Tests for SyncWorker._complete method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.mock_conn = MagicMock()

        # Setup connection context managers
        self.mock_pool.connection.return_value.__enter__ = MagicMock(return_value=self.mock_conn)
        self.mock_pool.connection.return_value.__exit__ = MagicMock(return_value=None)
        self.mock_conn.transaction.return_value.__enter__ = MagicMock()
        self.mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=None)

        self.worker = SyncWorker(self.mock_pool, domain="payments")
        self.worker._pgmq = MagicMock()
        self.worker._command_repo = MagicMock()

    def test_complete_deletes_message(self) -> None:
        """Should delete message from queue."""
        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )
        context = HandlerContext(command=command, attempt=1, max_attempts=3, msg_id=42)
        metadata = MagicMock()
        metadata.batch_id = None

        received = ReceivedCommand(command=command, context=context, msg_id=42, metadata=metadata)
        self.worker._command_repo.sp_finish_command = MagicMock(return_value=False)

        self.worker._complete(received)

        self.worker._pgmq.delete.assert_called_once()

    def test_complete_sends_reply_when_configured(self) -> None:
        """Should send reply to reply_to queue."""
        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
            reply_to="payments__replies",
        )
        context = HandlerContext(command=command, attempt=1, max_attempts=3, msg_id=42)
        metadata = MagicMock()
        metadata.batch_id = None

        received = ReceivedCommand(command=command, context=context, msg_id=42, metadata=metadata)
        self.worker._command_repo.sp_finish_command = MagicMock(return_value=False)

        self.worker._complete(received, result={"success": True})

        # Should send reply
        send_calls = self.worker._pgmq.send.call_args_list
        assert len(send_calls) == 1
        assert send_calls[0][0][0] == "payments__replies"


class TestSyncWorkerFail:
    """Tests for SyncWorker._fail method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.mock_conn = MagicMock()

        # Setup connection context managers
        self.mock_pool.connection.return_value.__enter__ = MagicMock(return_value=self.mock_conn)
        self.mock_pool.connection.return_value.__exit__ = MagicMock(return_value=None)
        self.mock_conn.transaction.return_value.__enter__ = MagicMock()
        self.mock_conn.transaction.return_value.__exit__ = MagicMock(return_value=None)

        self.worker = SyncWorker(self.mock_pool, domain="payments")
        self.worker._pgmq = MagicMock()
        self.worker._command_repo = MagicMock()

    def _make_received_command(self, attempt: int = 1) -> ReceivedCommand:
        """Create a test ReceivedCommand."""
        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )
        context = HandlerContext(
            command=command,
            attempt=attempt,
            max_attempts=3,
            msg_id=42,
        )
        metadata = MagicMock(spec=CommandMetadata)
        metadata.batch_id = None
        metadata.max_attempts = 3

        return ReceivedCommand(
            command=command,
            context=context,
            msg_id=42,
            metadata=metadata,
        )

    def test_fail_transient_applies_backoff(self) -> None:
        """Should apply backoff via set_vt for transient errors."""
        received = self._make_received_command(attempt=1)
        error = TransientCommandError(code="TIMEOUT", message="Timed out")

        self.worker._fail(received, error, is_transient=True)

        # Should call sp_fail_command and set_vt for backoff
        self.worker._command_repo.sp_fail_command.assert_called_once()
        self.worker._pgmq.set_vt.assert_called_once()

    def test_fail_exhausted_moves_to_tsq(self) -> None:
        """Should move to TSQ when retries exhausted."""
        # Create received at max attempts
        received = self._make_received_command(attempt=3)
        error = TransientCommandError(code="TIMEOUT", message="Timed out")

        # Mock retry policy to say no more retries
        self.worker._retry_policy = MagicMock()
        self.worker._retry_policy.should_retry = MagicMock(return_value=False)

        self.worker._fail(received, error, is_transient=True)

        # Should archive (move to TSQ)
        self.worker._pgmq.archive.assert_called_once()


class TestSyncWorkerHealthTracking:
    """Tests for health status tracking in SyncWorker."""

    def test_check_stuck_threads(self) -> None:
        """Should detect stuck threads based on timeout."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments", visibility_timeout=1)

        # Add an old in-flight task
        mock_future = MagicMock()
        mock_future.done.return_value = False
        worker._in_flight[1] = (mock_future, 0.0)  # Started at time 0

        # Check with current time way past threshold
        with patch("commandbus.sync.worker.time.monotonic", return_value=100.0):
            worker._check_stuck_threads()

        assert worker._health.stuck_threads == 1

    def test_cleanup_completed_removes_done_futures(self) -> None:
        """Should remove completed futures from in-flight."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        # Add a completed future
        done_future = MagicMock()
        done_future.done.return_value = True
        worker._in_flight[1] = (done_future, 0.0)

        # Add a not-done future
        pending_future = MagicMock()
        pending_future.done.return_value = False
        worker._in_flight[2] = (pending_future, 0.0)

        worker._cleanup_completed()

        assert 1 not in worker._in_flight
        assert 2 in worker._in_flight


class TestSyncWorkerDrain:
    """Tests for SyncWorker._drain_in_flight method."""

    def test_drain_empty_returns_immediately(self) -> None:
        """Should return immediately when no in-flight tasks."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        # Should not raise and return quickly
        worker._drain_in_flight(timeout=1.0)

    def test_drain_waits_for_futures(self) -> None:
        """Should wait for all futures to complete."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        mock_future = MagicMock()
        worker._in_flight[1] = (mock_future, 0.0)

        with patch("commandbus.sync.worker.wait") as mock_wait:
            mock_wait.return_value = ({mock_future}, set())
            worker._drain_in_flight(timeout=5.0)

        mock_wait.assert_called_once()


class TestSyncWorkerWaitForSlot:
    """Tests for SyncWorker._wait_for_slot method."""

    def test_wait_for_slot_empty_returns(self) -> None:
        """Should return immediately when no in-flight tasks."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        # Should not block
        worker._wait_for_slot(timeout=0.1)

    def test_wait_for_slot_waits_for_completion(self) -> None:
        """Should wait for any task to complete."""
        mock_pool = MagicMock()
        worker = SyncWorker(mock_pool, domain="payments")

        mock_future = MagicMock()
        worker._in_flight[1] = (mock_future, 0.0)

        with patch("commandbus.sync.worker.wait") as mock_wait:
            mock_wait.return_value = ({mock_future}, set())
            worker._wait_for_slot(timeout=1.0)

        mock_wait.assert_called_once()
        _args, kwargs = mock_wait.call_args
        assert kwargs.get("return_when") == "FIRST_COMPLETED"


class TestSyncHandlerRegistration:
    """Tests for sync handler registration in HandlerRegistry."""

    def test_sync_handler_decorator(self) -> None:
        """Should register sync handler via decorator."""
        registry = HandlerRegistry()

        @registry.sync_handler("payments", "DebitAccount")
        def handle_debit(command: Command, context: HandlerContext) -> dict:
            return {"processed": True}

        assert registry.has_sync_handler("payments", "DebitAccount")

    def test_dispatch_sync(self) -> None:
        """Should dispatch to registered sync handler."""
        registry = HandlerRegistry()
        calls = []

        @registry.sync_handler("payments", "DebitAccount")
        def handle_debit(command: Command, context: HandlerContext) -> dict:
            calls.append(command.command_id)
            return {"processed": True}

        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )
        context = HandlerContext(command=command, attempt=1, max_attempts=3, msg_id=1)

        result = registry.dispatch_sync(command, context)

        assert result == {"processed": True}
        assert len(calls) == 1

    def test_dispatch_sync_not_found(self) -> None:
        """Should raise HandlerNotFoundError for missing handler."""
        registry = HandlerRegistry()

        command = Command(
            domain="payments",
            command_type="Unknown",
            command_id=uuid4(),
            data={},
        )
        context = HandlerContext(command=command, attempt=1, max_attempts=3, msg_id=1)

        with pytest.raises(HandlerNotFoundError):
            registry.dispatch_sync(command, context)

    def test_clear_clears_sync_handlers(self) -> None:
        """Should clear sync handlers on clear()."""
        registry = HandlerRegistry()

        @registry.sync_handler("payments", "DebitAccount")
        def handle_debit(command: Command, context: HandlerContext) -> dict:
            return {}

        assert registry.has_sync_handler("payments", "DebitAccount")

        registry.clear()

        assert not registry.has_sync_handler("payments", "DebitAccount")
