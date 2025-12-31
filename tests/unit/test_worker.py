"""Unit tests for Worker receive functionality."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from commandbus.models import Command, CommandMetadata, CommandStatus, HandlerContext
from commandbus.pgmq.client import PgmqMessage
from commandbus.repositories.audit import AuditEventType
from commandbus.worker import ReceivedCommand, Worker


class TestWorkerInit:
    """Tests for Worker initialization."""

    def test_worker_init(self) -> None:
        """Test worker initialization."""
        pool = MagicMock()
        worker = Worker(pool, domain="payments")

        assert worker.domain == "payments"
        assert worker.queue_name == "payments__commands"

    def test_worker_custom_visibility_timeout(self) -> None:
        """Test worker with custom visibility timeout."""
        pool = MagicMock()
        worker = Worker(pool, domain="payments", visibility_timeout=60)

        assert worker._visibility_timeout == 60


class TestWorkerReceive:
    """Tests for Worker.receive()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        pool.connection = mock_connection
        return pool

    @pytest.fixture
    def worker(self, mock_pool: MagicMock) -> Worker:
        """Create a worker with mocked pool."""
        return Worker(mock_pool, domain="payments")

    @pytest.mark.asyncio
    async def test_receive_returns_command(self, worker: Worker) -> None:
        """Test receiving a command from the queue."""
        command_id = uuid4()
        correlation_id = uuid4()
        now = datetime.now(UTC)

        pgmq_message = PgmqMessage(
            msg_id=42,
            read_count=1,
            enqueued_at=str(now),
            vt=str(now),
            message={
                "domain": "payments",
                "command_type": "DebitAccount",
                "command_id": str(command_id),
                "correlation_id": str(correlation_id),
                "data": {"account_id": "123", "amount": 100},
            },
        )

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.PENDING,
            attempts=0,
            max_attempts=3,
            msg_id=42,
            correlation_id=correlation_id,
            created_at=now,
            updated_at=now,
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(worker._command_repo, "get", new_callable=AsyncMock) as mock_get,
            patch.object(
                worker._command_repo, "increment_attempts", new_callable=AsyncMock
            ) as mock_increment,
            patch.object(worker._command_repo, "update_status", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_read.return_value = [pgmq_message]
            mock_get.return_value = metadata
            mock_increment.return_value = 1

            results = await worker.receive(batch_size=1)

            assert len(results) == 1
            result = results[0]
            assert result.command.command_id == command_id
            assert result.command.command_type == "DebitAccount"
            assert result.context.attempt == 1
            assert result.msg_id == 42

    @pytest.mark.asyncio
    async def test_receive_empty_queue(self, worker: Worker) -> None:
        """Test receiving from an empty queue."""
        with patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read:
            mock_read.return_value = []

            results = await worker.receive()

            assert results == []
            mock_read.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_increments_attempts(self, worker: Worker) -> None:
        """Test that receive increments attempts counter."""
        command_id = uuid4()
        now = datetime.now(UTC)

        pgmq_message = PgmqMessage(
            msg_id=42,
            read_count=1,
            enqueued_at=str(now),
            vt=str(now),
            message={
                "domain": "payments",
                "command_type": "DebitAccount",
                "command_id": str(command_id),
                "data": {},
            },
        )

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.PENDING,
            attempts=0,
            max_attempts=3,
            created_at=now,
            updated_at=now,
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(worker._command_repo, "get", new_callable=AsyncMock) as mock_get,
            patch.object(
                worker._command_repo, "increment_attempts", new_callable=AsyncMock
            ) as mock_increment,
            patch.object(worker._command_repo, "update_status", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_read.return_value = [pgmq_message]
            mock_get.return_value = metadata
            mock_increment.return_value = 2  # Second attempt

            results = await worker.receive()

            mock_increment.assert_called_once_with("payments", command_id)
            assert results[0].context.attempt == 2

    @pytest.mark.asyncio
    async def test_receive_records_audit_event(self, worker: Worker) -> None:
        """Test that receive records RECEIVED audit event."""
        command_id = uuid4()
        now = datetime.now(UTC)

        pgmq_message = PgmqMessage(
            msg_id=42,
            read_count=1,
            enqueued_at=str(now),
            vt=str(now),
            message={
                "domain": "payments",
                "command_type": "DebitAccount",
                "command_id": str(command_id),
                "data": {},
            },
        )

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.PENDING,
            attempts=0,
            max_attempts=3,
            created_at=now,
            updated_at=now,
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(worker._command_repo, "get", new_callable=AsyncMock) as mock_get,
            patch.object(
                worker._command_repo, "increment_attempts", new_callable=AsyncMock
            ) as mock_increment,
            patch.object(worker._command_repo, "update_status", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock) as mock_audit,
        ):
            mock_read.return_value = [pgmq_message]
            mock_get.return_value = metadata
            mock_increment.return_value = 1

            await worker.receive()

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args[1]
            assert call_kwargs["domain"] == "payments"
            assert call_kwargs["command_id"] == command_id
            assert call_kwargs["event_type"] == AuditEventType.RECEIVED
            assert call_kwargs["details"]["attempt"] == 1

    @pytest.mark.asyncio
    async def test_receive_skips_completed_command(self, worker: Worker) -> None:
        """Test that completed commands are archived and skipped."""
        command_id = uuid4()
        now = datetime.now(UTC)

        pgmq_message = PgmqMessage(
            msg_id=42,
            read_count=1,
            enqueued_at=str(now),
            vt=str(now),
            message={
                "domain": "payments",
                "command_type": "DebitAccount",
                "command_id": str(command_id),
                "data": {},
            },
        )

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.COMPLETED,  # Terminal state
            attempts=1,
            max_attempts=3,
            created_at=now,
            updated_at=now,
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(worker._command_repo, "get", new_callable=AsyncMock) as mock_get,
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock) as mock_archive,
        ):
            mock_read.return_value = [pgmq_message]
            mock_get.return_value = metadata

            results = await worker.receive()

            assert results == []
            mock_archive.assert_called_once_with("payments__commands", 42)

    @pytest.mark.asyncio
    async def test_receive_skips_canceled_command(self, worker: Worker) -> None:
        """Test that canceled commands are archived and skipped."""
        command_id = uuid4()
        now = datetime.now(UTC)

        pgmq_message = PgmqMessage(
            msg_id=42,
            read_count=1,
            enqueued_at=str(now),
            vt=str(now),
            message={
                "domain": "payments",
                "command_type": "DebitAccount",
                "command_id": str(command_id),
                "data": {},
            },
        )

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.CANCELED,  # Terminal state
            attempts=1,
            max_attempts=3,
            created_at=now,
            updated_at=now,
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(worker._command_repo, "get", new_callable=AsyncMock) as mock_get,
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock) as mock_archive,
        ):
            mock_read.return_value = [pgmq_message]
            mock_get.return_value = metadata

            results = await worker.receive()

            assert results == []
            mock_archive.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_archives_missing_metadata(self, worker: Worker) -> None:
        """Test that messages without metadata are archived."""
        command_id = uuid4()
        now = datetime.now(UTC)

        pgmq_message = PgmqMessage(
            msg_id=42,
            read_count=1,
            enqueued_at=str(now),
            vt=str(now),
            message={
                "domain": "payments",
                "command_type": "DebitAccount",
                "command_id": str(command_id),
                "data": {},
            },
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(worker._command_repo, "get", new_callable=AsyncMock) as mock_get,
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock) as mock_archive,
        ):
            mock_read.return_value = [pgmq_message]
            mock_get.return_value = None  # No metadata

            results = await worker.receive()

            assert results == []
            mock_archive.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_archives_missing_command_id(self, worker: Worker) -> None:
        """Test that messages without command_id are archived."""
        now = datetime.now(UTC)

        pgmq_message = PgmqMessage(
            msg_id=42,
            read_count=1,
            enqueued_at=str(now),
            vt=str(now),
            message={
                "domain": "payments",
                "command_type": "DebitAccount",
                # Missing command_id
                "data": {},
            },
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock) as mock_archive,
        ):
            mock_read.return_value = [pgmq_message]

            results = await worker.receive()

            assert results == []
            mock_archive.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_updates_status_to_in_progress(self, worker: Worker) -> None:
        """Test that receive updates command status to IN_PROGRESS."""
        command_id = uuid4()
        now = datetime.now(UTC)

        pgmq_message = PgmqMessage(
            msg_id=42,
            read_count=1,
            enqueued_at=str(now),
            vt=str(now),
            message={
                "domain": "payments",
                "command_type": "DebitAccount",
                "command_id": str(command_id),
                "data": {},
            },
        )

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.PENDING,
            attempts=0,
            max_attempts=3,
            created_at=now,
            updated_at=now,
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(worker._command_repo, "get", new_callable=AsyncMock) as mock_get,
            patch.object(
                worker._command_repo, "increment_attempts", new_callable=AsyncMock
            ) as mock_increment,
            patch.object(
                worker._command_repo, "update_status", new_callable=AsyncMock
            ) as mock_update_status,
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_read.return_value = [pgmq_message]
            mock_get.return_value = metadata
            mock_increment.return_value = 1

            await worker.receive()

            mock_update_status.assert_called_once_with(
                "payments", command_id, CommandStatus.IN_PROGRESS
            )

    @pytest.mark.asyncio
    async def test_receive_with_custom_visibility_timeout(self, worker: Worker) -> None:
        """Test receive with custom visibility timeout."""
        with patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read:
            mock_read.return_value = []

            await worker.receive(visibility_timeout=60)

            mock_read.assert_called_once_with(
                "payments__commands",
                visibility_timeout=60,
                batch_size=1,
            )

    @pytest.mark.asyncio
    async def test_receive_with_batch_size(self, worker: Worker) -> None:
        """Test receive with batch size."""
        with patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read:
            mock_read.return_value = []

            await worker.receive(batch_size=10)

            mock_read.assert_called_once_with(
                "payments__commands",
                visibility_timeout=30,
                batch_size=10,
            )


class TestWorkerComplete:
    """Tests for Worker.complete()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with transaction support."""
        pool = MagicMock()
        conn = MagicMock()
        transaction = MagicMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        @asynccontextmanager
        async def mock_transaction():
            yield transaction

        pool.connection = mock_connection
        conn.transaction = mock_transaction
        return pool

    @pytest.fixture
    def worker(self, mock_pool: MagicMock) -> Worker:
        """Create a worker with mocked pool."""
        return Worker(mock_pool, domain="payments")

    @pytest.fixture
    def received_command(self) -> ReceivedCommand:
        """Create a received command for testing."""
        command_id = uuid4()
        correlation_id = uuid4()
        now = datetime.now(UTC)

        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123", "amount": 100},
            correlation_id=correlation_id,
            reply_to=None,
            created_at=now,
        )

        context = HandlerContext(
            command=command,
            attempt=1,
            max_attempts=3,
            msg_id=42,
        )

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.IN_PROGRESS,
            attempts=1,
            max_attempts=3,
            created_at=now,
            updated_at=now,
        )

        return ReceivedCommand(
            command=command,
            context=context,
            msg_id=42,
            metadata=metadata,
        )

    @pytest.mark.asyncio
    async def test_complete_deletes_message(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that complete deletes the message from the queue."""
        with (
            patch.object(worker._pgmq, "delete", new_callable=AsyncMock) as mock_delete,
            patch.object(worker._command_repo, "update_status", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_delete.return_value = True

            await worker.complete(received_command)

            mock_delete.assert_called_once()
            call_args = mock_delete.call_args
            assert call_args[0][0] == "payments__commands"
            assert call_args[0][1] == 42

    @pytest.mark.asyncio
    async def test_complete_updates_status_to_completed(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that complete updates status to COMPLETED."""
        with (
            patch.object(worker._pgmq, "delete", new_callable=AsyncMock),
            patch.object(
                worker._command_repo, "update_status", new_callable=AsyncMock
            ) as mock_update,
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            await worker.complete(received_command)

            mock_update.assert_called_once()
            call_args = mock_update.call_args
            assert call_args[0][0] == "payments"
            assert call_args[0][1] == received_command.command.command_id
            assert call_args[0][2] == CommandStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_complete_records_audit_event(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that complete records COMPLETED audit event."""
        with (
            patch.object(worker._pgmq, "delete", new_callable=AsyncMock),
            patch.object(worker._command_repo, "update_status", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock) as mock_audit,
        ):
            await worker.complete(received_command)

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args[1]
            assert call_kwargs["domain"] == "payments"
            assert call_kwargs["command_id"] == received_command.command.command_id
            assert call_kwargs["event_type"] == AuditEventType.COMPLETED
            assert call_kwargs["details"]["msg_id"] == 42

    @pytest.mark.asyncio
    async def test_complete_with_reply_to_sends_reply(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that complete sends reply when reply_to is configured."""
        # Modify command to have reply_to
        command = Command(
            domain=received_command.command.domain,
            command_type=received_command.command.command_type,
            command_id=received_command.command.command_id,
            data=received_command.command.data,
            correlation_id=received_command.command.correlation_id,
            reply_to="reports__replies",
            created_at=received_command.command.created_at,
        )
        received_with_reply = ReceivedCommand(
            command=command,
            context=received_command.context,
            msg_id=received_command.msg_id,
            metadata=received_command.metadata,
        )

        with (
            patch.object(worker._pgmq, "delete", new_callable=AsyncMock),
            patch.object(worker._pgmq, "send", new_callable=AsyncMock) as mock_send,
            patch.object(worker._command_repo, "update_status", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            await worker.complete(received_with_reply, result={"status": "ok"})

            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][0] == "reports__replies"
            reply_message = call_args[0][1]
            assert reply_message["command_id"] == str(command.command_id)
            assert reply_message["outcome"] == "SUCCESS"
            assert reply_message["result"] == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_complete_without_reply_to_does_not_send(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that complete does not send reply when reply_to is None."""
        with (
            patch.object(worker._pgmq, "delete", new_callable=AsyncMock),
            patch.object(worker._pgmq, "send", new_callable=AsyncMock) as mock_send,
            patch.object(worker._command_repo, "update_status", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            await worker.complete(received_command)

            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_with_result(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that complete includes result in audit details."""
        with (
            patch.object(worker._pgmq, "delete", new_callable=AsyncMock),
            patch.object(worker._command_repo, "update_status", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock) as mock_audit,
        ):
            await worker.complete(received_command, result={"status": "processed"})

            call_kwargs = mock_audit.call_args[1]
            assert call_kwargs["details"]["has_result"] is True


class TestWorkerRun:
    """Tests for Worker.run() and related methods."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with transaction support."""
        pool = MagicMock()
        conn = MagicMock()
        transaction = MagicMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        @asynccontextmanager
        async def mock_transaction():
            yield transaction

        pool.connection = mock_connection
        conn.transaction = mock_transaction
        return pool

    @pytest.fixture
    def mock_registry(self) -> MagicMock:
        """Create a mock handler registry."""
        registry = MagicMock()
        registry.dispatch = AsyncMock(return_value={"processed": True})
        return registry

    @pytest.fixture
    def worker(self, mock_pool: MagicMock, mock_registry: MagicMock) -> Worker:
        """Create a worker with mocked pool and registry."""
        return Worker(mock_pool, domain="payments", registry=mock_registry)

    def test_worker_init_with_registry(self, worker: Worker) -> None:
        """Test worker initialization with registry."""
        assert worker._registry is not None
        assert worker._running is False
        assert worker._stop_event is None
        assert len(worker._in_flight) == 0

    def test_is_running_property(self, worker: Worker) -> None:
        """Test is_running property."""
        assert worker.is_running is False
        worker._running = True
        assert worker.is_running is True

    def test_in_flight_count_property(self, worker: Worker) -> None:
        """Test in_flight_count property."""
        assert worker.in_flight_count == 0

    @pytest.mark.asyncio
    async def test_run_without_registry_raises_error(self, mock_pool: MagicMock) -> None:
        """Test that run raises error without registry."""
        worker = Worker(mock_pool, domain="payments")
        with pytest.raises(RuntimeError, match="Cannot run worker without a handler registry"):
            await worker.run()

    @pytest.mark.asyncio
    async def test_run_sets_running_flag(self, worker: Worker) -> None:
        """Test that run sets the running flag."""
        with patch.object(worker, "_run_with_polling", new_callable=AsyncMock) as mock_run:

            async def stop_after_start(*args: object, **kwargs: object) -> None:
                await asyncio.sleep(0.01)
                await worker.stop()

            mock_run.side_effect = stop_after_start

            await worker.run(use_notify=False)

    @pytest.mark.asyncio
    async def test_stop_sets_event(self, worker: Worker) -> None:
        """Test that stop sets the stop event."""
        worker._running = True
        worker._stop_event = asyncio.Event()

        await worker.stop()

        assert worker._stop_event.is_set()

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self, worker: Worker) -> None:
        """Test that stop does nothing when not running."""
        await worker.stop()  # Should not raise

    @pytest.mark.asyncio
    async def test_process_batch_receives_commands(self, worker: Worker) -> None:
        """Test that _process_batch receives and processes commands."""
        command_id = uuid4()
        now = datetime.now(UTC)

        received = ReceivedCommand(
            command=Command(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={},
                created_at=now,
            ),
            context=HandlerContext(
                command=MagicMock(),
                attempt=1,
                max_attempts=3,
                msg_id=42,
            ),
            msg_id=42,
            metadata=MagicMock(),
        )

        semaphore = asyncio.Semaphore(5)

        with (
            patch.object(worker, "receive", new_callable=AsyncMock) as mock_receive,
            patch.object(worker, "_process_command", new_callable=AsyncMock),
        ):
            mock_receive.return_value = [received]

            await worker._process_batch(semaphore)

            mock_receive.assert_called_once_with(batch_size=5)

    @pytest.mark.asyncio
    async def test_process_batch_skips_when_no_slots(self, worker: Worker) -> None:
        """Test that _process_batch skips when no slots available."""
        semaphore = asyncio.Semaphore(0)

        with patch.object(worker, "receive", new_callable=AsyncMock) as mock_receive:
            await worker._process_batch(semaphore)

            mock_receive.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_command_dispatches_and_completes(self, worker: Worker) -> None:
        """Test that _process_command dispatches and completes."""
        command_id = uuid4()
        now = datetime.now(UTC)

        received = ReceivedCommand(
            command=Command(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={},
                created_at=now,
            ),
            context=HandlerContext(
                command=MagicMock(),
                attempt=1,
                max_attempts=3,
                msg_id=42,
            ),
            msg_id=42,
            metadata=MagicMock(),
        )

        semaphore = asyncio.Semaphore(1)

        with patch.object(worker, "complete", new_callable=AsyncMock) as mock_complete:
            await worker._process_command(received, semaphore)

            mock_complete.assert_called_once()
            call_kwargs = mock_complete.call_args[1]
            assert call_kwargs["result"] == {"processed": True}

    @pytest.mark.asyncio
    async def test_process_command_handles_errors(
        self, worker: Worker, mock_registry: MagicMock
    ) -> None:
        """Test that _process_command handles handler errors gracefully."""
        command_id = uuid4()
        now = datetime.now(UTC)

        received = ReceivedCommand(
            command=Command(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={},
                created_at=now,
            ),
            context=HandlerContext(
                command=MagicMock(),
                attempt=1,
                max_attempts=3,
                msg_id=42,
            ),
            msg_id=42,
            metadata=MagicMock(),
        )

        semaphore = asyncio.Semaphore(1)
        mock_registry.dispatch.side_effect = Exception("Handler failed")

        with patch.object(worker, "complete", new_callable=AsyncMock) as mock_complete:
            # Should not raise
            await worker._process_command(received, semaphore)

            # Complete should not be called on error
            mock_complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_for_in_flight(self, worker: Worker) -> None:
        """Test _wait_for_in_flight waits for tasks."""
        task1_done = asyncio.Event()
        task2_done = asyncio.Event()

        async def slow_task1() -> None:
            await asyncio.sleep(0.01)
            task1_done.set()

        async def slow_task2() -> None:
            await asyncio.sleep(0.01)
            task2_done.set()

        worker._in_flight.add(asyncio.create_task(slow_task1()))
        worker._in_flight.add(asyncio.create_task(slow_task2()))

        await worker._wait_for_in_flight()

        assert task1_done.is_set()
        assert task2_done.is_set()
