"""Unit tests for batch creation functionality."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from commandbus.bus import CommandBus
from commandbus.exceptions import DuplicateCommandError
from commandbus.models import (
    BatchCommand,
    BatchMetadata,
    BatchStatus,
    CreateBatchResult,
    SendResult,
)


class TestBatchCommand:
    """Tests for BatchCommand dataclass."""

    def test_batch_command_creation(self) -> None:
        """Test creating a BatchCommand."""
        cmd_id = uuid4()
        cmd = BatchCommand(
            command_type="DebitAccount",
            command_id=cmd_id,
            data={"account_id": "123", "amount": 100},
        )

        assert cmd.command_type == "DebitAccount"
        assert cmd.command_id == cmd_id
        assert cmd.data == {"account_id": "123", "amount": 100}
        assert cmd.correlation_id is None
        assert cmd.reply_to is None
        assert cmd.max_attempts is None

    def test_batch_command_with_optional_fields(self) -> None:
        """Test creating a BatchCommand with optional fields."""
        cmd_id = uuid4()
        corr_id = uuid4()
        cmd = BatchCommand(
            command_type="DebitAccount",
            command_id=cmd_id,
            data={"account_id": "123"},
            correlation_id=corr_id,
            reply_to="payments__replies",
            max_attempts=5,
        )

        assert cmd.correlation_id == corr_id
        assert cmd.reply_to == "payments__replies"
        assert cmd.max_attempts == 5


class TestBatchMetadata:
    """Tests for BatchMetadata dataclass."""

    def test_batch_metadata_creation(self) -> None:
        """Test creating a BatchMetadata."""
        batch_id = uuid4()
        now = datetime.now(UTC)
        metadata = BatchMetadata(
            domain="payments",
            batch_id=batch_id,
            status=BatchStatus.PENDING,
            name="Test Batch",
            total_count=3,
            created_at=now,
        )

        assert metadata.domain == "payments"
        assert metadata.batch_id == batch_id
        assert metadata.status == BatchStatus.PENDING
        assert metadata.name == "Test Batch"
        assert metadata.total_count == 3
        assert metadata.completed_count == 0
        assert metadata.failed_count == 0
        assert metadata.canceled_count == 0
        assert metadata.in_troubleshooting_count == 0
        assert metadata.started_at is None
        assert metadata.completed_at is None

    def test_batch_metadata_with_custom_data(self) -> None:
        """Test creating a BatchMetadata with custom data."""
        batch_id = uuid4()
        custom = {"source": "csv", "file_id": "abc123"}
        metadata = BatchMetadata(
            domain="payments",
            batch_id=batch_id,
            custom_data=custom,
        )

        assert metadata.custom_data == custom


class TestBatchStatus:
    """Tests for BatchStatus enum."""

    def test_batch_status_values(self) -> None:
        """Test BatchStatus enum values."""
        assert BatchStatus.PENDING.value == "PENDING"
        assert BatchStatus.IN_PROGRESS.value == "IN_PROGRESS"
        assert BatchStatus.COMPLETED.value == "COMPLETED"
        assert BatchStatus.COMPLETED_WITH_FAILURES.value == "COMPLETED_WITH_FAILURES"


class TestCreateBatchResult:
    """Tests for CreateBatchResult dataclass."""

    def test_create_batch_result(self) -> None:
        """Test creating a CreateBatchResult."""
        batch_id = uuid4()
        cmd_id = uuid4()
        result = CreateBatchResult(
            batch_id=batch_id,
            command_results=[SendResult(command_id=cmd_id, msg_id=1)],
            total_commands=1,
        )

        assert result.batch_id == batch_id
        assert len(result.command_results) == 1
        assert result.total_commands == 1


class TestCommandBusCreateBatch:
    """Tests for CommandBus.create_batch() method."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with proper async context managers."""
        pool = MagicMock()
        conn = MagicMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        @asynccontextmanager
        async def mock_transaction():
            yield None

        pool.connection = mock_connection
        conn.transaction = mock_transaction

        return pool

    @pytest.fixture
    def command_bus(self, mock_pool: MagicMock) -> CommandBus:
        """Create a CommandBus with mocked dependencies."""
        return CommandBus(mock_pool, default_max_attempts=3)

    @pytest.mark.asyncio
    async def test_create_batch_success(self, command_bus: CommandBus) -> None:
        """Test creating a batch with multiple commands."""
        batch_id = uuid4()
        cmd1_id = uuid4()
        cmd2_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(
                command_bus._batch_repo, "save", new_callable=AsyncMock
            ) as mock_batch_save,
            patch.object(command_bus._pgmq, "send_batch", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(
                command_bus._command_repo, "save_batch", new_callable=AsyncMock
            ) as mock_cmd_save,
            patch.object(
                command_bus._audit_logger, "log_batch", new_callable=AsyncMock
            ) as mock_audit,
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock) as mock_notify,
        ):
            mock_exists.return_value = set()
            mock_pgmq_send.return_value = [1, 2]

            result = await command_bus.create_batch(
                domain="payments",
                commands=[
                    BatchCommand(
                        command_type="DebitAccount",
                        command_id=cmd1_id,
                        data={"account_id": "123", "amount": 100},
                    ),
                    BatchCommand(
                        command_type="DebitAccount",
                        command_id=cmd2_id,
                        data={"account_id": "456", "amount": 200},
                    ),
                ],
                batch_id=batch_id,
                name="Test Batch",
            )

            assert result.batch_id == batch_id
            assert result.total_commands == 2
            assert len(result.command_results) == 2
            assert result.command_results[0].command_id == cmd1_id
            assert result.command_results[0].msg_id == 1
            assert result.command_results[1].command_id == cmd2_id
            assert result.command_results[1].msg_id == 2

            mock_exists.assert_called_once()
            mock_batch_save.assert_called_once()
            mock_pgmq_send.assert_called_once()
            mock_cmd_save.assert_called_once()
            mock_audit.assert_called_once()
            mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_batch_sets_total_count(self, command_bus: CommandBus) -> None:
        """Test that total_count is set correctly in batch metadata."""
        batch_id = uuid4()
        saved_batch: BatchMetadata | None = None

        async def capture_batch(metadata: BatchMetadata, conn: MagicMock) -> None:
            nonlocal saved_batch
            saved_batch = metadata

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._batch_repo, "save", side_effect=capture_batch),
            patch.object(command_bus._pgmq, "send_batch", new_callable=AsyncMock) as mock_send,
            patch.object(command_bus._command_repo, "save_batch", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists.return_value = set()
            mock_send.return_value = [1, 2, 3]

            await command_bus.create_batch(
                domain="payments",
                commands=[
                    BatchCommand(command_type="Cmd", command_id=uuid4(), data={}) for _ in range(3)
                ],
                batch_id=batch_id,
            )

            assert saved_batch is not None
            assert saved_batch.total_count == 3
            assert saved_batch.status == BatchStatus.PENDING
            assert saved_batch.completed_count == 0

    @pytest.mark.asyncio
    async def test_create_batch_links_commands(self, command_bus: CommandBus) -> None:
        """Test that commands have batch_id set."""
        batch_id = uuid4()
        saved_commands: list = []

        async def capture_commands(metadata_list: list, queue: str, conn: MagicMock) -> None:
            saved_commands.extend(metadata_list)

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._batch_repo, "save", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "send_batch", new_callable=AsyncMock) as mock_send,
            patch.object(command_bus._command_repo, "save_batch", side_effect=capture_commands),
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists.return_value = set()
            mock_send.return_value = [1, 2]

            await command_bus.create_batch(
                domain="payments",
                commands=[
                    BatchCommand(command_type="Cmd", command_id=uuid4(), data={}) for _ in range(2)
                ],
                batch_id=batch_id,
            )

            assert len(saved_commands) == 2
            for cmd in saved_commands:
                assert cmd.batch_id == batch_id

    @pytest.mark.asyncio
    async def test_create_batch_rejects_empty(self, command_bus: CommandBus) -> None:
        """Test that empty batch is rejected."""
        with pytest.raises(ValueError, match="Batch must contain at least one command"):
            await command_bus.create_batch(
                domain="payments",
                commands=[],
            )

    @pytest.mark.asyncio
    async def test_create_batch_duplicate_in_batch(self, command_bus: CommandBus) -> None:
        """Test that duplicate command_ids in the same batch are rejected."""
        cmd_id = uuid4()

        with pytest.raises(DuplicateCommandError):
            await command_bus.create_batch(
                domain="payments",
                commands=[
                    BatchCommand(command_type="Cmd", command_id=cmd_id, data={}),
                    BatchCommand(command_type="Cmd", command_id=cmd_id, data={}),
                ],
            )

    @pytest.mark.asyncio
    async def test_create_batch_duplicate_in_database(self, command_bus: CommandBus) -> None:
        """Test that duplicate command_ids in database are rejected."""
        existing_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists,
        ):
            mock_exists.return_value = {existing_id}

            with pytest.raises(DuplicateCommandError):
                await command_bus.create_batch(
                    domain="payments",
                    commands=[
                        BatchCommand(
                            command_type="Cmd",
                            command_id=existing_id,
                            data={},
                        ),
                    ],
                )

    @pytest.mark.asyncio
    async def test_create_batch_generates_batch_id(self, command_bus: CommandBus) -> None:
        """Test that batch_id is generated if not provided."""
        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._batch_repo, "save", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "send_batch", new_callable=AsyncMock) as mock_send,
            patch.object(command_bus._command_repo, "save_batch", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists.return_value = set()
            mock_send.return_value = [1]

            result = await command_bus.create_batch(
                domain="payments",
                commands=[BatchCommand(command_type="Cmd", command_id=uuid4(), data={})],
            )

            assert result.batch_id is not None

    @pytest.mark.asyncio
    async def test_create_batch_with_custom_data(self, command_bus: CommandBus) -> None:
        """Test creating a batch with custom metadata."""
        saved_batch: BatchMetadata | None = None
        custom = {"source": "csv", "file_id": "abc123"}

        async def capture_batch(metadata: BatchMetadata, conn: MagicMock) -> None:
            nonlocal saved_batch
            saved_batch = metadata

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._batch_repo, "save", side_effect=capture_batch),
            patch.object(command_bus._pgmq, "send_batch", new_callable=AsyncMock) as mock_send,
            patch.object(command_bus._command_repo, "save_batch", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists.return_value = set()
            mock_send.return_value = [1]

            await command_bus.create_batch(
                domain="payments",
                commands=[BatchCommand(command_type="Cmd", command_id=uuid4(), data={})],
                name="Import job 12345",
                custom_data=custom,
            )

            assert saved_batch is not None
            assert saved_batch.name == "Import job 12345"
            assert saved_batch.custom_data == custom

    @pytest.mark.asyncio
    async def test_create_batch_uses_default_max_attempts(self, command_bus: CommandBus) -> None:
        """Test that commands inherit default max_attempts."""
        saved_commands: list = []

        async def capture_commands(metadata_list: list, queue: str, conn: MagicMock) -> None:
            saved_commands.extend(metadata_list)

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._batch_repo, "save", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "send_batch", new_callable=AsyncMock) as mock_send,
            patch.object(command_bus._command_repo, "save_batch", side_effect=capture_commands),
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists.return_value = set()
            mock_send.return_value = [1]

            await command_bus.create_batch(
                domain="payments",
                commands=[BatchCommand(command_type="Cmd", command_id=uuid4(), data={})],
            )

            assert len(saved_commands) == 1
            assert saved_commands[0].max_attempts == 3  # default

    @pytest.mark.asyncio
    async def test_create_batch_respects_command_max_attempts(
        self, command_bus: CommandBus
    ) -> None:
        """Test that command-level max_attempts overrides default."""
        saved_commands: list = []

        async def capture_commands(metadata_list: list, queue: str, conn: MagicMock) -> None:
            saved_commands.extend(metadata_list)

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._batch_repo, "save", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "send_batch", new_callable=AsyncMock) as mock_send,
            patch.object(command_bus._command_repo, "save_batch", side_effect=capture_commands),
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists.return_value = set()
            mock_send.return_value = [1]

            await command_bus.create_batch(
                domain="payments",
                commands=[
                    BatchCommand(command_type="Cmd", command_id=uuid4(), data={}, max_attempts=5)
                ],
            )

            assert len(saved_commands) == 1
            assert saved_commands[0].max_attempts == 5

    @pytest.mark.asyncio
    async def test_create_batch_audit_includes_batch_id(self, command_bus: CommandBus) -> None:
        """Test that audit events include batch_id."""
        batch_id = uuid4()
        logged_events: list = []

        async def capture_audit(events: list, conn: MagicMock) -> None:
            logged_events.extend(events)

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._batch_repo, "save", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "send_batch", new_callable=AsyncMock) as mock_send,
            patch.object(command_bus._command_repo, "save_batch", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log_batch", side_effect=capture_audit),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists.return_value = set()
            mock_send.return_value = [1]

            await command_bus.create_batch(
                domain="payments",
                commands=[BatchCommand(command_type="Cmd", command_id=uuid4(), data={})],
                batch_id=batch_id,
            )

            assert len(logged_events) == 1
            _domain, _cmd_id, _event_type, details = logged_events[0]
            assert details["batch_id"] == str(batch_id)
