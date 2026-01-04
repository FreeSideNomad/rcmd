"""Unit tests for batch creation functionality."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from commandbus.batch import (
    _batch_callbacks,
    check_and_invoke_batch_callback,
    clear_all_callbacks,
    get_batch_callback,
    register_batch_callback,
    remove_batch_callback,
)
from commandbus.bus import CommandBus
from commandbus.exceptions import DuplicateCommandError
from commandbus.models import (
    BatchCommand,
    BatchMetadata,
    BatchStatus,
    CreateBatchResult,
    SendResult,
)
from commandbus.repositories.batch import PostgresBatchRepository


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

    @pytest.mark.asyncio
    async def test_create_batch_registers_on_complete_callback(
        self, command_bus: CommandBus
    ) -> None:
        """Test that on_complete callback is registered."""
        clear_all_callbacks()

        batch_id = uuid4()
        callback = AsyncMock()

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

            await command_bus.create_batch(
                domain="payments",
                commands=[BatchCommand(command_type="Cmd", command_id=uuid4(), data={})],
                batch_id=batch_id,
                on_complete=callback,
            )

            registered = get_batch_callback("payments", batch_id)
            assert registered is callback

        clear_all_callbacks()

    @pytest.mark.asyncio
    async def test_create_batch_without_on_complete_callback(self, command_bus: CommandBus) -> None:
        """Test that no callback is registered when on_complete is not provided."""
        clear_all_callbacks()

        batch_id = uuid4()

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

            await command_bus.create_batch(
                domain="payments",
                commands=[BatchCommand(command_type="Cmd", command_id=uuid4(), data={})],
                batch_id=batch_id,
            )

            registered = get_batch_callback("payments", batch_id)
            assert registered is None

        clear_all_callbacks()


class TestBatchRepositoryStatusTracking:
    """Tests for PostgresBatchRepository status tracking methods."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with proper async context managers."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        @asynccontextmanager
        async def mock_cursor():
            yield cursor

        pool.connection = mock_connection
        conn.cursor = mock_cursor

        return pool, conn, cursor

    @pytest.mark.asyncio
    async def test_update_on_receive_returns_true(self, mock_pool: tuple) -> None:
        """Test update_on_receive returns True when batch transitions."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_receive("payments", uuid4())

        assert result is True
        cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_on_receive_returns_false(self, mock_pool: tuple) -> None:
        """Test update_on_receive returns False when no transition."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(False,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_receive("payments", uuid4())

        assert result is False

    @pytest.mark.asyncio
    async def test_update_on_receive_with_conn(self, mock_pool: tuple) -> None:
        """Test update_on_receive uses provided connection."""
        pool, conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_receive("payments", uuid4(), conn=conn)

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_complete_returns_true(self, mock_pool: tuple) -> None:
        """Test update_on_complete returns True when batch updated."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_complete("payments", uuid4())

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_complete_with_conn(self, mock_pool: tuple) -> None:
        """Test update_on_complete uses provided connection."""
        pool, conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_complete("payments", uuid4(), conn=conn)

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_tsq_move_returns_true(self, mock_pool: tuple) -> None:
        """Test update_on_tsq_move returns True when batch updated."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_tsq_move("payments", uuid4())

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_tsq_move_with_conn(self, mock_pool: tuple) -> None:
        """Test update_on_tsq_move uses provided connection."""
        pool, conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_tsq_move("payments", uuid4(), conn=conn)

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_tsq_complete_returns_true(self, mock_pool: tuple) -> None:
        """Test update_on_tsq_complete returns True when batch updated."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_tsq_complete("payments", uuid4())

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_tsq_complete_with_conn(self, mock_pool: tuple) -> None:
        """Test update_on_tsq_complete uses provided connection."""
        pool, conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_tsq_complete("payments", uuid4(), conn=conn)

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_tsq_cancel_returns_true(self, mock_pool: tuple) -> None:
        """Test update_on_tsq_cancel returns True when batch updated."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_tsq_cancel("payments", uuid4())

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_tsq_cancel_with_conn(self, mock_pool: tuple) -> None:
        """Test update_on_tsq_cancel uses provided connection."""
        pool, conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_tsq_cancel("payments", uuid4(), conn=conn)

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_tsq_retry_returns_true(self, mock_pool: tuple) -> None:
        """Test update_on_tsq_retry returns True when batch updated."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_tsq_retry("payments", uuid4())

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_tsq_retry_with_conn(self, mock_pool: tuple) -> None:
        """Test update_on_tsq_retry uses provided connection."""
        pool, conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_tsq_retry("payments", uuid4(), conn=conn)

        assert result is True

    @pytest.mark.asyncio
    async def test_update_on_receive_handles_none_row(self, mock_pool: tuple) -> None:
        """Test update_on_receive handles None row result."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=None)

        repo = PostgresBatchRepository(pool)
        result = await repo.update_on_receive("payments", uuid4())

        assert result is False


class TestBatchCompletionCallbackRegistry:
    """Tests for batch completion callback registry functions."""

    @pytest.fixture(autouse=True)
    def cleanup_callbacks(self) -> None:
        """Clear all callbacks before and after each test."""
        clear_all_callbacks()
        yield
        clear_all_callbacks()

    @pytest.mark.asyncio
    async def test_register_and_get_callback(self) -> None:
        """Test registering and retrieving a callback."""
        batch_id = uuid4()
        callback = AsyncMock()

        await register_batch_callback("payments", batch_id, callback)

        retrieved = get_batch_callback("payments", batch_id)
        assert retrieved is callback

    @pytest.mark.asyncio
    async def test_get_callback_not_found(self) -> None:
        """Test getting a callback that doesn't exist."""
        result = get_batch_callback("payments", uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_remove_callback(self) -> None:
        """Test removing a callback."""
        batch_id = uuid4()
        callback = AsyncMock()

        await register_batch_callback("payments", batch_id, callback)
        await remove_batch_callback("payments", batch_id)

        result = get_batch_callback("payments", batch_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_callback(self) -> None:
        """Test removing a callback that doesn't exist (no error)."""
        # Should not raise
        await remove_batch_callback("payments", uuid4())

    def test_clear_all_callbacks(self) -> None:
        """Test clearing all callbacks."""
        # Add some callbacks directly
        _batch_callbacks[("payments", uuid4())] = AsyncMock()
        _batch_callbacks[("orders", uuid4())] = AsyncMock()

        clear_all_callbacks()

        assert len(_batch_callbacks) == 0

    @pytest.mark.asyncio
    async def test_callbacks_are_domain_scoped(self) -> None:
        """Test that callbacks are scoped by domain."""
        batch_id = uuid4()
        callback1 = AsyncMock()
        callback2 = AsyncMock()

        await register_batch_callback("payments", batch_id, callback1)
        await register_batch_callback("orders", batch_id, callback2)

        assert get_batch_callback("payments", batch_id) is callback1
        assert get_batch_callback("orders", batch_id) is callback2

    @pytest.mark.asyncio
    async def test_check_and_invoke_callback_not_registered(self) -> None:
        """Test check_and_invoke when no callback is registered."""
        batch_repo = MagicMock()
        batch_repo.get = AsyncMock()

        # Should not call batch_repo.get if no callback registered
        await check_and_invoke_batch_callback("payments", uuid4(), batch_repo)

        batch_repo.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_check_and_invoke_callback_batch_not_found(self) -> None:
        """Test check_and_invoke when batch doesn't exist."""
        batch_id = uuid4()
        callback = AsyncMock()

        await register_batch_callback("payments", batch_id, callback)

        batch_repo = MagicMock()
        batch_repo.get = AsyncMock(return_value=None)

        await check_and_invoke_batch_callback("payments", batch_id, batch_repo)

        callback.assert_not_called()
        # Callback should be removed
        assert get_batch_callback("payments", batch_id) is None

    @pytest.mark.asyncio
    async def test_check_and_invoke_callback_batch_not_terminal(self) -> None:
        """Test check_and_invoke when batch is not in terminal state."""
        batch_id = uuid4()
        callback = AsyncMock()

        await register_batch_callback("payments", batch_id, callback)

        batch = BatchMetadata(
            domain="payments",
            batch_id=batch_id,
            status=BatchStatus.IN_PROGRESS,
        )
        batch_repo = MagicMock()
        batch_repo.get = AsyncMock(return_value=batch)

        await check_and_invoke_batch_callback("payments", batch_id, batch_repo)

        callback.assert_not_called()
        # Callback should still be registered
        assert get_batch_callback("payments", batch_id) is callback

    @pytest.mark.asyncio
    async def test_check_and_invoke_callback_completed(self) -> None:
        """Test check_and_invoke when batch is COMPLETED."""

        batch_id = uuid4()
        callback = AsyncMock()

        await register_batch_callback("payments", batch_id, callback)

        batch = BatchMetadata(
            domain="payments",
            batch_id=batch_id,
            status=BatchStatus.COMPLETED,
        )
        batch_repo = MagicMock()
        batch_repo.get = AsyncMock(return_value=batch)

        await check_and_invoke_batch_callback("payments", batch_id, batch_repo)

        callback.assert_called_once_with(batch)
        # Callback should be removed after invocation
        assert get_batch_callback("payments", batch_id) is None

    @pytest.mark.asyncio
    async def test_check_and_invoke_callback_completed_with_failures(self) -> None:
        """Test check_and_invoke when batch is COMPLETED_WITH_FAILURES."""
        batch_id = uuid4()
        callback = AsyncMock()

        await register_batch_callback("payments", batch_id, callback)

        batch = BatchMetadata(
            domain="payments",
            batch_id=batch_id,
            status=BatchStatus.COMPLETED_WITH_FAILURES,
            failed_count=2,
        )
        batch_repo = MagicMock()
        batch_repo.get = AsyncMock(return_value=batch)

        await check_and_invoke_batch_callback("payments", batch_id, batch_repo)

        callback.assert_called_once_with(batch)
        assert get_batch_callback("payments", batch_id) is None

    @pytest.mark.asyncio
    async def test_check_and_invoke_callback_exception_isolated(self) -> None:
        """Test that callback exceptions are caught and don't propagate."""
        batch_id = uuid4()
        callback = AsyncMock(side_effect=ValueError("callback failed"))

        await register_batch_callback("payments", batch_id, callback)

        batch = BatchMetadata(
            domain="payments",
            batch_id=batch_id,
            status=BatchStatus.COMPLETED,
        )
        batch_repo = MagicMock()
        batch_repo.get = AsyncMock(return_value=batch)

        # Should not raise
        await check_and_invoke_batch_callback("payments", batch_id, batch_repo)

        callback.assert_called_once()
        # Callback should still be removed after failure
        assert get_batch_callback("payments", batch_id) is None
