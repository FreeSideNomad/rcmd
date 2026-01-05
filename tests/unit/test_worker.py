"""Unit tests for Worker receive functionality."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from commandbus.exceptions import PermanentCommandError, TransientCommandError
from commandbus.models import Command, CommandMetadata, CommandStatus, HandlerContext
from commandbus.pgmq.client import PgmqMessage
from commandbus.policies import RetryPolicy
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
        """Create a mock connection pool with proper async support."""
        pool = MagicMock()
        conn = MagicMock()
        # Make execute awaitable
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def mock_transaction():
            yield

        conn.transaction = mock_transaction

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

        # Metadata reflecting what sp_receive_command returns
        updated_metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.IN_PROGRESS,
            attempts=1,
            max_attempts=3,
            msg_id=42,
            correlation_id=correlation_id,
            created_at=now,
            updated_at=now,
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(
                worker._command_repo, "sp_receive_command", new_callable=AsyncMock
            ) as mock_receive_cmd,
        ):
            mock_read.return_value = [pgmq_message]
            mock_receive_cmd.return_value = (updated_metadata, 1)

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

        # receive_command returns metadata with incremented attempts
        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.IN_PROGRESS,
            attempts=2,  # Second attempt
            max_attempts=3,
            created_at=now,
            updated_at=now,
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(
                worker._command_repo, "sp_receive_command", new_callable=AsyncMock
            ) as mock_receive_cmd,
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_read.return_value = [pgmq_message]
            mock_receive_cmd.return_value = (metadata, 2)  # Second attempt

            results = await worker.receive()

            mock_receive_cmd.assert_called_once()
            call_args = mock_receive_cmd.call_args[0]
            assert call_args[0] == "payments"
            assert call_args[1] == command_id
            assert results[0].context.attempt == 2

    @pytest.mark.asyncio
    async def test_receive_calls_sp_with_msg_id(self, worker: Worker) -> None:
        """Test that receive calls sp_receive_command with correct msg_id."""
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
            status=CommandStatus.IN_PROGRESS,
            attempts=1,
            max_attempts=3,
            created_at=now,
            updated_at=now,
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(
                worker._command_repo, "sp_receive_command", new_callable=AsyncMock
            ) as mock_receive_cmd,
        ):
            mock_read.return_value = [pgmq_message]
            mock_receive_cmd.return_value = (metadata, 1)

            await worker.receive()

            # Verify sp_receive_command was called with msg_id for audit logging
            mock_receive_cmd.assert_called_once()
            call_kwargs = mock_receive_cmd.call_args[1]
            assert call_kwargs["msg_id"] == 42

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

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(
                worker._command_repo, "sp_receive_command", new_callable=AsyncMock
            ) as mock_receive_cmd,
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock) as mock_archive,
        ):
            mock_read.return_value = [pgmq_message]
            # receive_command returns None for terminal states (COMPLETED, CANCELED)
            mock_receive_cmd.return_value = None

            results = await worker.receive()

            assert results == []
            mock_archive.assert_called_once()
            call_args = mock_archive.call_args[0]
            assert call_args[0] == "payments__commands"
            assert call_args[1] == 42
            # 3rd arg is conn (shared connection)

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

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(
                worker._command_repo, "sp_receive_command", new_callable=AsyncMock
            ) as mock_receive_cmd,
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock) as mock_archive,
        ):
            mock_read.return_value = [pgmq_message]
            # receive_command returns None for terminal states (COMPLETED, CANCELED)
            mock_receive_cmd.return_value = None

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
            patch.object(
                worker._command_repo, "sp_receive_command", new_callable=AsyncMock
            ) as mock_receive_cmd,
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock) as mock_archive,
        ):
            mock_read.return_value = [pgmq_message]
            mock_receive_cmd.return_value = None  # No metadata

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

        # receive_command atomically increments attempts and updates status
        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.IN_PROGRESS,  # Status after receive_command
            attempts=1,
            max_attempts=3,
            created_at=now,
            updated_at=now,
        )

        with (
            patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read,
            patch.object(
                worker._command_repo, "sp_receive_command", new_callable=AsyncMock
            ) as mock_receive_cmd,
        ):
            mock_read.return_value = [pgmq_message]
            mock_receive_cmd.return_value = (metadata, 1)

            await worker.receive()

            # sp_receive_command is called with domain and command_id
            mock_receive_cmd.assert_called_once()
            call_args = mock_receive_cmd.call_args[0]
            assert call_args[0] == "payments"
            assert call_args[1] == command_id

    @pytest.mark.asyncio
    async def test_receive_with_custom_visibility_timeout(self, worker: Worker) -> None:
        """Test receive with custom visibility timeout."""
        with patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read:
            mock_read.return_value = []

            await worker.receive(visibility_timeout=60)

            mock_read.assert_called_once()
            call_kwargs = mock_read.call_args[1]
            assert call_kwargs["visibility_timeout"] == 60
            assert call_kwargs["batch_size"] == 1
            # conn is also passed as kwarg

    @pytest.mark.asyncio
    async def test_receive_with_batch_size(self, worker: Worker) -> None:
        """Test receive with batch size."""
        with patch.object(worker._pgmq, "read", new_callable=AsyncMock) as mock_read:
            mock_read.return_value = []

            await worker.receive(batch_size=10)

            mock_read.assert_called_once()
            call_kwargs = mock_read.call_args[1]
            assert call_kwargs["visibility_timeout"] == 30
            assert call_kwargs["batch_size"] == 10
            # conn is also passed as kwarg


class TestWorkerComplete:
    """Tests for Worker.complete()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with transaction support."""
        pool = MagicMock()
        conn = MagicMock()
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        @asynccontextmanager
        async def mock_transaction():
            yield

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
            patch.object(worker._command_repo, "sp_finish_command", new_callable=AsyncMock),
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
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
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
    async def test_complete_calls_sp_with_audit_params(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that complete calls sp_finish_command with audit parameters."""
        with (
            patch.object(worker._pgmq, "delete", new_callable=AsyncMock),
            patch.object(
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
            ) as mock_sp_finish,
        ):
            await worker.complete(received_command)

            mock_sp_finish.assert_called_once()
            call_kwargs = mock_sp_finish.call_args[1]
            # SP handles audit internally with these parameters
            assert call_kwargs["event_type"] == "COMPLETED"
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
            patch.object(worker._command_repo, "sp_finish_command", new_callable=AsyncMock),
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
            patch.object(worker._command_repo, "sp_finish_command", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            await worker.complete(received_command)

            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_complete_with_result(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that complete includes result in sp_finish_command details."""
        with (
            patch.object(worker._pgmq, "delete", new_callable=AsyncMock),
            patch.object(
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
            ) as mock_sp_finish,
        ):
            await worker.complete(received_command, result={"status": "processed"})

            call_kwargs = mock_sp_finish.call_args[1]
            assert call_kwargs["details"]["has_result"] is True


class TestWorkerRun:
    """Tests for Worker.run() and related methods."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with transaction support."""
        pool = MagicMock()
        conn = MagicMock()
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        @asynccontextmanager
        async def mock_transaction():
            yield

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
    async def test_drain_queue_receives_commands(self, worker: Worker) -> None:
        """Test that _drain_queue receives and processes commands."""
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
        worker._stop_event = asyncio.Event()

        with (
            patch.object(worker, "receive", new_callable=AsyncMock) as mock_receive,
            patch.object(worker, "_process_command", new_callable=AsyncMock),
        ):
            # Return commands first call, then empty to exit loop
            mock_receive.side_effect = [[received], []]

            await worker._drain_queue(semaphore)

            assert mock_receive.call_count == 2
            mock_receive.assert_any_call(batch_size=5)

    @pytest.mark.asyncio
    async def test_drain_queue_waits_for_slot(self, worker: Worker) -> None:
        """Test that _drain_queue waits when no slots available."""
        semaphore = asyncio.Semaphore(0)
        worker._stop_event = asyncio.Event()
        worker._in_flight = set()

        with patch.object(worker, "receive", new_callable=AsyncMock) as mock_receive:
            # Set stop event to exit immediately after waiting for slot
            worker._stop_event.set()

            await worker._drain_queue(semaphore)

            # Should not have called receive since no slots and stop was set
            mock_receive.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_command_dispatches_and_completes(self, worker: Worker) -> None:
        """Test that _process_command dispatches and completes within transaction."""
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

        # Now _process_command calls _complete_in_txn within transaction
        with patch.object(worker, "_complete_in_txn", new_callable=AsyncMock) as mock_complete:
            await worker._process_command(received, semaphore)

            mock_complete.assert_called_once()
            # First positional arg is received, second is result, third is conn
            args = mock_complete.call_args[0]
            assert args[0] is received
            assert args[1] == {"processed": True}  # result from handler

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

        with (
            patch.object(worker, "complete", new_callable=AsyncMock) as mock_complete,
            patch.object(worker, "fail", new_callable=AsyncMock) as mock_fail,
        ):
            # Should not raise
            await worker._process_command(received, semaphore)

            # Complete should not be called on error
            mock_complete.assert_not_called()
            # Fail should be called for error handling
            mock_fail.assert_called_once()

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


class TestWorkerFail:
    """Tests for Worker.fail() transient error handling."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        @asynccontextmanager
        async def mock_transaction():
            yield

        pool.connection = mock_connection
        conn.transaction = mock_transaction
        return pool

    @pytest.fixture
    def worker(self, mock_pool: MagicMock) -> Worker:
        """Create a worker with mocked pool."""
        return Worker(
            mock_pool,
            domain="payments",
            retry_policy=RetryPolicy(max_attempts=3, backoff_schedule=[10, 60, 300]),
        )

    @pytest.fixture
    def received_command(self) -> ReceivedCommand:
        """Create a received command for testing."""
        command_id = uuid4()
        now = datetime.now(UTC)

        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123", "amount": 100},
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
    async def test_fail_updates_error_metadata(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that fail updates error metadata."""
        error = TransientCommandError("TIMEOUT", "Connection timeout")

        with (
            patch.object(
                worker._command_repo, "sp_fail_command", new_callable=AsyncMock
            ) as mock_sp_fail,
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
            patch.object(worker._pgmq, "set_vt", new_callable=AsyncMock),
        ):
            await worker.fail(received_command, error)

            mock_sp_fail.assert_called_once()
            call_args = mock_sp_fail.call_args[0]
            assert call_args[0] == "payments"
            assert call_args[1] == received_command.command.command_id
            assert call_args[2] == "TRANSIENT"
            assert call_args[3] == "TIMEOUT"
            assert call_args[4] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_fail_calls_sp_with_audit_params(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that fail calls sp_fail_command which handles audit internally."""
        error = TransientCommandError("TIMEOUT", "Connection timeout")

        with (
            patch.object(
                worker._command_repo, "sp_fail_command", new_callable=AsyncMock
            ) as mock_sp_fail,
            patch.object(worker._pgmq, "set_vt", new_callable=AsyncMock),
        ):
            await worker.fail(received_command, error)

            # sp_fail_command is called with all error details; it handles audit internally
            mock_sp_fail.assert_called_once()
            call_args = mock_sp_fail.call_args[0]
            assert call_args[0] == "payments"  # domain
            assert call_args[1] == received_command.command.command_id  # command_id
            assert call_args[2] == "TRANSIENT"  # error_type
            assert call_args[3] == "TIMEOUT"  # error_code
            assert call_args[4] == "Connection timeout"  # error_msg

    @pytest.mark.asyncio
    async def test_fail_applies_backoff_via_set_vt(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that fail applies backoff by setting visibility timeout."""
        error = TransientCommandError("TIMEOUT", "Connection timeout")

        with (
            patch.object(worker._command_repo, "sp_fail_command", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
            patch.object(worker._pgmq, "set_vt", new_callable=AsyncMock) as mock_set_vt,
        ):
            await worker.fail(received_command, error)

            # Attempt 1 -> backoff schedule index 0 -> 10 seconds
            mock_set_vt.assert_called_once()
            call_args = mock_set_vt.call_args[0]
            assert call_args[0] == "payments__commands"
            assert call_args[1] == 42
            assert call_args[2] == 10
            # 4th arg is conn (shared connection)

    @pytest.mark.asyncio
    async def test_fail_backoff_increases_with_attempts(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that backoff increases with each attempt."""
        # Modify to attempt 2
        context = HandlerContext(
            command=received_command.command,
            attempt=2,
            max_attempts=3,
            msg_id=42,
        )
        received = ReceivedCommand(
            command=received_command.command,
            context=context,
            msg_id=42,
            metadata=received_command.metadata,
        )

        error = TransientCommandError("TIMEOUT", "Connection timeout")

        with (
            patch.object(worker._command_repo, "sp_fail_command", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
            patch.object(worker._pgmq, "set_vt", new_callable=AsyncMock) as mock_set_vt,
        ):
            await worker.fail(received, error)

            # Attempt 2 -> backoff schedule index 1 -> 60 seconds
            mock_set_vt.assert_called_once()
            call_args = mock_set_vt.call_args[0]
            assert call_args[0] == "payments__commands"
            assert call_args[1] == 42
            assert call_args[2] == 60
            # 4th arg is conn (shared connection)

    @pytest.mark.asyncio
    async def test_fail_calls_exhausted_at_max_attempts(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that fail calls _fail_exhausted at max attempts."""
        # Modify to max attempts
        context = HandlerContext(
            command=received_command.command,
            attempt=3,  # max_attempts
            max_attempts=3,
            msg_id=42,
        )
        received = ReceivedCommand(
            command=received_command.command,
            context=context,
            msg_id=42,
            metadata=received_command.metadata,
        )

        error = TransientCommandError("TIMEOUT", "Connection timeout")

        with (
            patch.object(worker, "_fail_exhausted", new_callable=AsyncMock) as mock_fail_exhausted,
            patch.object(worker._pgmq, "set_vt", new_callable=AsyncMock) as mock_set_vt,
        ):
            await worker.fail(received, error)

            # At max attempts, should call _fail_exhausted instead of set_vt
            mock_fail_exhausted.assert_called_once_with(
                received, "TRANSIENT", "TIMEOUT", "Connection timeout"
            )
            mock_set_vt.assert_not_called()

    @pytest.mark.asyncio
    async def test_fail_handles_unknown_exception(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that fail handles unknown exceptions as transient."""
        error = ValueError("Some unexpected error")

        with (
            patch.object(
                worker._command_repo, "sp_fail_command", new_callable=AsyncMock
            ) as mock_sp_fail,
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
            patch.object(worker._pgmq, "set_vt", new_callable=AsyncMock),
        ):
            await worker.fail(received_command, error)

            # Unknown exception treated as transient
            mock_sp_fail.assert_called_once()
            call_args = mock_sp_fail.call_args[0]
            assert call_args[2] == "TRANSIENT"
            assert call_args[3] == "ValueError"
            assert call_args[4] == "Some unexpected error"

    @pytest.mark.asyncio
    async def test_fail_handles_permanent_error(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that fail handles permanent errors (no backoff applied)."""
        error = PermanentCommandError("INVALID_DATA", "Missing required field")

        with (
            patch.object(
                worker._command_repo, "sp_fail_command", new_callable=AsyncMock
            ) as mock_sp_fail,
            patch.object(worker._pgmq, "set_vt", new_callable=AsyncMock) as mock_set_vt,
        ):
            await worker.fail(received_command, error, is_transient=False)

            mock_sp_fail.assert_called_once()
            call_args = mock_sp_fail.call_args[0]
            assert call_args[2] == "PERMANENT"
            assert call_args[3] == "INVALID_DATA"
            assert call_args[4] == "Missing required field"
            # Permanent errors should not apply backoff
            mock_set_vt.assert_not_called()


class TestWorkerTransientErrorHandling:
    """Tests for automatic transient error handling in _process_command."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        @asynccontextmanager
        async def mock_transaction():
            yield

        pool.connection = mock_connection
        conn.transaction = mock_transaction
        return pool

    @pytest.fixture
    def mock_registry(self) -> MagicMock:
        """Create a mock handler registry."""
        registry = MagicMock()
        registry.dispatch = AsyncMock()
        return registry

    @pytest.fixture
    def worker(self, mock_pool: MagicMock, mock_registry: MagicMock) -> Worker:
        """Create a worker with mocked pool and registry."""
        return Worker(mock_pool, domain="payments", registry=mock_registry)

    @pytest.fixture
    def received_command(self) -> ReceivedCommand:
        """Create a received command for testing."""
        command_id = uuid4()
        now = datetime.now(UTC)

        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={},
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
    async def test_process_command_handles_transient_error(
        self,
        worker: Worker,
        mock_registry: MagicMock,
        received_command: ReceivedCommand,
    ) -> None:
        """Test that _process_command handles TransientCommandError."""
        mock_registry.dispatch.side_effect = TransientCommandError("TIMEOUT", "Timed out")
        semaphore = asyncio.Semaphore(1)

        with patch.object(worker, "fail", new_callable=AsyncMock) as mock_fail:
            await worker._process_command(received_command, semaphore)

            mock_fail.assert_called_once()
            call_args = mock_fail.call_args
            assert call_args[0][0] == received_command
            assert isinstance(call_args[0][1], TransientCommandError)
            assert call_args[1]["is_transient"] is True

    @pytest.mark.asyncio
    async def test_process_command_handles_permanent_error(
        self,
        worker: Worker,
        mock_registry: MagicMock,
        received_command: ReceivedCommand,
    ) -> None:
        """Test that _process_command handles PermanentCommandError."""
        mock_registry.dispatch.side_effect = PermanentCommandError("INVALID", "Invalid data")
        semaphore = asyncio.Semaphore(1)

        with patch.object(worker, "fail_permanent", new_callable=AsyncMock) as mock_fail_permanent:
            await worker._process_command(received_command, semaphore)

            mock_fail_permanent.assert_called_once()
            call_args = mock_fail_permanent.call_args
            assert call_args[0][0] == received_command
            assert isinstance(call_args[0][1], PermanentCommandError)

    @pytest.mark.asyncio
    async def test_process_command_treats_unknown_as_transient(
        self,
        worker: Worker,
        mock_registry: MagicMock,
        received_command: ReceivedCommand,
    ) -> None:
        """Test that _process_command treats unknown exceptions as transient."""
        mock_registry.dispatch.side_effect = RuntimeError("Something broke")
        semaphore = asyncio.Semaphore(1)

        with patch.object(worker, "fail", new_callable=AsyncMock) as mock_fail:
            await worker._process_command(received_command, semaphore)

            mock_fail.assert_called_once()
            call_args = mock_fail.call_args
            assert isinstance(call_args[0][1], RuntimeError)
            assert call_args[1]["is_transient"] is True


class TestWorkerFailPermanent:
    """Tests for Worker.fail_permanent() permanent error handling."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with transaction support."""
        pool = MagicMock()
        conn = MagicMock()
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        @asynccontextmanager
        async def mock_transaction():
            yield

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
        now = datetime.now(UTC)

        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123", "amount": 100},
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
    async def test_fail_permanent_archives_message(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that fail_permanent archives the message."""
        error = PermanentCommandError("INVALID_ACCOUNT", "Account not found")

        with (
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock) as mock_archive,
            patch.object(worker._command_repo, "sp_finish_command", new_callable=AsyncMock),
            patch.object(worker._command_repo, "sp_fail_command", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            await worker.fail_permanent(received_command, error)

            mock_archive.assert_called_once()
            call_args = mock_archive.call_args
            assert call_args[0][0] == "payments__commands"
            assert call_args[0][1] == 42

    @pytest.mark.asyncio
    async def test_fail_permanent_sets_tsq_status(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that fail_permanent sets status to IN_TROUBLESHOOTING_QUEUE."""
        error = PermanentCommandError("INVALID_ACCOUNT", "Account not found")

        with (
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock),
            patch.object(
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
            ) as mock_finish_command,
            patch.object(worker._command_repo, "sp_fail_command", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            await worker.fail_permanent(received_command, error)

            mock_finish_command.assert_called_once()
            call_args = mock_finish_command.call_args
            assert call_args[0][0] == "payments"
            assert call_args[0][1] == received_command.command.command_id
            assert call_args[0][2] == CommandStatus.IN_TROUBLESHOOTING_QUEUE

    @pytest.mark.asyncio
    async def test_fail_permanent_stores_error_details(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that fail_permanent stores error details in metadata via finish_command."""
        error = PermanentCommandError(
            "INVALID_ACCOUNT", "Account not found", details={"account_id": "xyz"}
        )

        with (
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock),
            patch.object(
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
            ) as mock_finish_command,
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            await worker.fail_permanent(received_command, error)

            mock_finish_command.assert_called_once()
            call_kwargs = mock_finish_command.call_args[1]
            assert call_kwargs["error_type"] == "PERMANENT"
            assert call_kwargs["error_code"] == "INVALID_ACCOUNT"
            assert call_kwargs["error_msg"] == "Account not found"

    @pytest.mark.asyncio
    async def test_fail_permanent_calls_sp_with_audit_params(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that fail_permanent calls sp_finish_command with audit parameters."""
        error = PermanentCommandError(
            "INVALID_ACCOUNT", "Account not found", details={"account_id": "xyz"}
        )

        with (
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock),
            patch.object(
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
            ) as mock_sp_finish,
        ):
            await worker.fail_permanent(received_command, error)

            mock_sp_finish.assert_called_once()
            call_kwargs = mock_sp_finish.call_args[1]
            # sp_finish_command handles audit internally with these parameters
            assert call_kwargs["event_type"] == "MOVED_TO_TSQ"
            assert call_kwargs["error_code"] == "INVALID_ACCOUNT"
            assert call_kwargs["error_msg"] == "Account not found"

    @pytest.mark.asyncio
    async def test_fail_permanent_first_attempt(
        self, worker: Worker, received_command: ReceivedCommand
    ) -> None:
        """Test that first attempt permanent failure goes directly to troubleshooting."""
        # Confirm attempt is 1
        assert received_command.context.attempt == 1

        error = PermanentCommandError("VALIDATION", "Missing required field")

        with (
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock) as mock_archive,
            patch.object(
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
            ) as mock_finish_command,
        ):
            await worker.fail_permanent(received_command, error)

            # Message should be archived
            mock_archive.assert_called_once()

            # Status should be IN_TROUBLESHOOTING_QUEUE
            call_args = mock_finish_command.call_args
            assert call_args[0][2] == CommandStatus.IN_TROUBLESHOOTING_QUEUE

            # sp_finish_command should include attempt in details
            call_kwargs = mock_finish_command.call_args[1]
            assert call_kwargs["details"]["attempt"] == 1


class TestWorkerFailExhausted:
    """Tests for Worker._fail_exhausted() retry exhaustion handling."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with transaction support."""
        pool = MagicMock()
        conn = MagicMock()
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        @asynccontextmanager
        async def mock_transaction():
            yield

        pool.connection = mock_connection
        conn.transaction = mock_transaction
        return pool

    @pytest.fixture
    def worker(self, mock_pool: MagicMock) -> Worker:
        """Create a worker with mocked pool."""
        return Worker(
            mock_pool,
            domain="payments",
            retry_policy=RetryPolicy(max_attempts=3, backoff_schedule=[10, 60, 300]),
        )

    @pytest.fixture
    def exhausted_command(self) -> ReceivedCommand:
        """Create a received command at max attempts (exhausted)."""
        command_id = uuid4()
        now = datetime.now(UTC)

        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123", "amount": 100},
            created_at=now,
        )

        context = HandlerContext(
            command=command,
            attempt=3,  # max_attempts reached
            max_attempts=3,
            msg_id=42,
        )

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.IN_PROGRESS,
            attempts=3,
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
    async def test_fail_exhausted_archives_message(
        self, worker: Worker, exhausted_command: ReceivedCommand
    ) -> None:
        """Test that _fail_exhausted archives the message."""
        with (
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock) as mock_archive,
            patch.object(worker._command_repo, "sp_finish_command", new_callable=AsyncMock),
            patch.object(worker._command_repo, "sp_fail_command", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            await worker._fail_exhausted(
                exhausted_command, "TRANSIENT", "TIMEOUT", "Connection timeout"
            )

            mock_archive.assert_called_once()
            call_args = mock_archive.call_args
            assert call_args[0][0] == "payments__commands"
            assert call_args[0][1] == 42

    @pytest.mark.asyncio
    async def test_fail_exhausted_sets_tsq_status(
        self, worker: Worker, exhausted_command: ReceivedCommand
    ) -> None:
        """Test that _fail_exhausted sets status to IN_TROUBLESHOOTING_QUEUE."""
        with (
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock),
            patch.object(
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
            ) as mock_finish_command,
            patch.object(worker._command_repo, "sp_fail_command", new_callable=AsyncMock),
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            await worker._fail_exhausted(
                exhausted_command, "TRANSIENT", "TIMEOUT", "Connection timeout"
            )

            mock_finish_command.assert_called_once()
            call_args = mock_finish_command.call_args
            assert call_args[0][0] == "payments"
            assert call_args[0][1] == exhausted_command.command.command_id
            assert call_args[0][2] == CommandStatus.IN_TROUBLESHOOTING_QUEUE

    @pytest.mark.asyncio
    async def test_fail_exhausted_stores_error_details(
        self, worker: Worker, exhausted_command: ReceivedCommand
    ) -> None:
        """Test that _fail_exhausted stores error details in metadata via finish_command."""
        with (
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock),
            patch.object(
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
            ) as mock_finish_command,
            patch.object(worker._audit_logger, "log", new_callable=AsyncMock),
        ):
            await worker._fail_exhausted(
                exhausted_command, "TRANSIENT", "TIMEOUT", "Connection timeout"
            )

            mock_finish_command.assert_called_once()
            call_kwargs = mock_finish_command.call_args[1]
            assert call_kwargs["error_type"] == "TRANSIENT"
            assert call_kwargs["error_code"] == "TIMEOUT"
            assert call_kwargs["error_msg"] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_fail_exhausted_calls_sp_with_audit_params(
        self, worker: Worker, exhausted_command: ReceivedCommand
    ) -> None:
        """Test that _fail_exhausted calls sp_finish_command with audit parameters."""
        with (
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock),
            patch.object(
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
            ) as mock_sp_finish,
        ):
            await worker._fail_exhausted(
                exhausted_command, "TRANSIENT", "TIMEOUT", "Connection timeout"
            )

            mock_sp_finish.assert_called_once()
            call_kwargs = mock_sp_finish.call_args[1]
            # sp_finish_command handles audit internally with these parameters
            assert call_kwargs["event_type"] == "MOVED_TO_TSQ"
            assert call_kwargs["details"]["reason"] == "EXHAUSTED"
            assert call_kwargs["details"]["attempt"] == 3
            assert call_kwargs["details"]["max_attempts"] == 3
            assert call_kwargs["error_type"] == "TRANSIENT"
            assert call_kwargs["error_code"] == "TIMEOUT"

    @pytest.mark.asyncio
    async def test_fail_exhausted_with_unknown_exception(
        self, worker: Worker, exhausted_command: ReceivedCommand
    ) -> None:
        """Test that _fail_exhausted handles unknown exceptions as transient via finish_command."""
        with (
            patch.object(worker._pgmq, "archive", new_callable=AsyncMock),
            patch.object(
                worker._command_repo, "sp_finish_command", new_callable=AsyncMock
            ) as mock_finish_command,
        ):
            await worker._fail_exhausted(
                exhausted_command, "TRANSIENT", "RuntimeError", "Unexpected error"
            )

            mock_finish_command.assert_called_once()
            call_kwargs = mock_finish_command.call_args[1]
            assert call_kwargs["error_type"] == "TRANSIENT"
            assert call_kwargs["error_code"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_fail_triggers_exhausted_for_transient_at_max(
        self, worker: Worker, exhausted_command: ReceivedCommand
    ) -> None:
        """Test that fail() triggers _fail_exhausted for transient errors at max attempts."""
        error = TransientCommandError("TIMEOUT", "Connection timeout")

        with patch.object(worker, "_fail_exhausted", new_callable=AsyncMock) as mock_exhausted:
            await worker.fail(exhausted_command, error)

            mock_exhausted.assert_called_once_with(
                exhausted_command, "TRANSIENT", "TIMEOUT", "Connection timeout"
            )

    @pytest.mark.asyncio
    async def test_fail_triggers_exhausted_for_unknown_at_max(
        self, worker: Worker, exhausted_command: ReceivedCommand
    ) -> None:
        """Test that fail() triggers _fail_exhausted for unknown exceptions at max attempts."""
        error = RuntimeError("Unexpected database error")

        with patch.object(worker, "_fail_exhausted", new_callable=AsyncMock) as mock_exhausted:
            await worker.fail(exhausted_command, error)

            mock_exhausted.assert_called_once_with(
                exhausted_command, "TRANSIENT", "RuntimeError", "Unexpected database error"
            )
