"""Unit tests for Worker receive functionality."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from commandbus.models import CommandMetadata, CommandStatus
from commandbus.pgmq.client import PgmqMessage
from commandbus.repositories.audit import AuditEventType
from commandbus.worker import Worker


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
