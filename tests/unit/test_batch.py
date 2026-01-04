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
from commandbus.exceptions import BatchNotFoundError, DuplicateCommandError
from commandbus.models import (
    BatchCommand,
    BatchMetadata,
    BatchStatus,
    CommandMetadata,
    CommandStatus,
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
    """Tests for PostgresBatchRepository TSQ status tracking methods."""

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
    async def test_tsq_complete_returns_true_when_batch_completes(self, mock_pool: tuple) -> None:
        """Test tsq_complete returns True when batch is now complete."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.tsq_complete("payments", uuid4())

        assert result is True
        cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_tsq_complete_returns_false_when_batch_not_complete(
        self, mock_pool: tuple
    ) -> None:
        """Test tsq_complete returns False when batch is not complete."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(False,))

        repo = PostgresBatchRepository(pool)
        result = await repo.tsq_complete("payments", uuid4())

        assert result is False

    @pytest.mark.asyncio
    async def test_tsq_complete_with_conn(self, mock_pool: tuple) -> None:
        """Test tsq_complete uses provided connection."""
        pool, conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.tsq_complete("payments", uuid4(), conn=conn)

        assert result is True

    @pytest.mark.asyncio
    async def test_tsq_cancel_returns_true_when_batch_completes(self, mock_pool: tuple) -> None:
        """Test tsq_cancel returns True when batch is now complete."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.tsq_cancel("payments", uuid4())

        assert result is True

    @pytest.mark.asyncio
    async def test_tsq_cancel_with_conn(self, mock_pool: tuple) -> None:
        """Test tsq_cancel uses provided connection."""
        pool, conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

        repo = PostgresBatchRepository(pool)
        result = await repo.tsq_cancel("payments", uuid4(), conn=conn)

        assert result is True

    @pytest.mark.asyncio
    async def test_tsq_retry_does_not_return_value(self, mock_pool: tuple) -> None:
        """Test tsq_retry returns None (never completes batch)."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()

        repo = PostgresBatchRepository(pool)
        result = await repo.tsq_retry("payments", uuid4())

        assert result is None
        cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_tsq_retry_with_conn(self, mock_pool: tuple) -> None:
        """Test tsq_retry uses provided connection."""
        pool, conn, cursor = mock_pool
        cursor.execute = AsyncMock()

        repo = PostgresBatchRepository(pool)
        await repo.tsq_retry("payments", uuid4(), conn=conn)

        cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_tsq_complete_handles_none_row(self, mock_pool: tuple) -> None:
        """Test tsq_complete handles None row result."""
        pool, _conn, cursor = mock_pool
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=None)

        repo = PostgresBatchRepository(pool)
        result = await repo.tsq_complete("payments", uuid4())

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
            canceled_count=2,
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


class TestCommandBusBatchQueries:
    """Tests for S044: Query Batches and Their Commands."""

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
    async def test_get_batch_returns_metadata(self, command_bus: CommandBus) -> None:
        """Test get_batch returns BatchMetadata when found."""
        batch_id = uuid4()
        expected = BatchMetadata(
            domain="payments",
            batch_id=batch_id,
            status=BatchStatus.IN_PROGRESS,
            total_count=5,
        )

        with patch.object(command_bus._batch_repo, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = expected

            result = await command_bus.get_batch("payments", batch_id)

            assert result == expected
            mock_get.assert_called_once_with("payments", batch_id)

    @pytest.mark.asyncio
    async def test_get_batch_returns_none(self, command_bus: CommandBus) -> None:
        """Test get_batch returns None when not found."""
        with patch.object(command_bus._batch_repo, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            result = await command_bus.get_batch("payments", uuid4())

            assert result is None

    @pytest.mark.asyncio
    async def test_get_batch_domain_scoped(self, command_bus: CommandBus) -> None:
        """Test get_batch is domain-scoped."""
        batch_id = uuid4()

        with patch.object(command_bus._batch_repo, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            # Batch exists in "payments" but we query "orders"
            await command_bus.get_batch("orders", batch_id)

            mock_get.assert_called_once_with("orders", batch_id)

    @pytest.mark.asyncio
    async def test_list_batches(self, command_bus: CommandBus) -> None:
        """Test list_batches returns list of BatchMetadata."""
        batches = [
            BatchMetadata(domain="payments", batch_id=uuid4(), status=BatchStatus.PENDING),
            BatchMetadata(domain="payments", batch_id=uuid4(), status=BatchStatus.IN_PROGRESS),
        ]

        with patch.object(
            command_bus._batch_repo, "list_batches", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = batches

            result = await command_bus.list_batches("payments")

            assert result == batches
            mock_list.assert_called_once_with(domain="payments", status=None, limit=100, offset=0)

    @pytest.mark.asyncio
    async def test_list_batches_status_filter(self, command_bus: CommandBus) -> None:
        """Test list_batches with status filter."""
        batches = [
            BatchMetadata(domain="payments", batch_id=uuid4(), status=BatchStatus.IN_PROGRESS),
        ]

        with patch.object(
            command_bus._batch_repo, "list_batches", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = batches

            result = await command_bus.list_batches("payments", status=BatchStatus.IN_PROGRESS)

            assert result == batches
            mock_list.assert_called_once_with(
                domain="payments", status=BatchStatus.IN_PROGRESS, limit=100, offset=0
            )

    @pytest.mark.asyncio
    async def test_list_batches_pagination(self, command_bus: CommandBus) -> None:
        """Test list_batches with pagination."""
        batches = [
            BatchMetadata(domain="payments", batch_id=uuid4(), status=BatchStatus.PENDING)
            for _ in range(10)
        ]

        with patch.object(
            command_bus._batch_repo, "list_batches", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = batches

            result = await command_bus.list_batches("payments", limit=10, offset=10)

            assert len(result) == 10
            mock_list.assert_called_once_with(domain="payments", status=None, limit=10, offset=10)

    @pytest.mark.asyncio
    async def test_list_batch_commands(self, command_bus: CommandBus) -> None:
        """Test list_batch_commands returns list of CommandMetadata."""
        batch_id = uuid4()
        now = datetime.now(UTC)
        commands = [
            CommandMetadata(
                domain="payments",
                command_id=uuid4(),
                command_type="DebitAccount",
                status=CommandStatus.PENDING,
                batch_id=batch_id,
                created_at=now,
                updated_at=now,
            ),
            CommandMetadata(
                domain="payments",
                command_id=uuid4(),
                command_type="DebitAccount",
                status=CommandStatus.COMPLETED,
                batch_id=batch_id,
                created_at=now,
                updated_at=now,
            ),
        ]

        with patch.object(
            command_bus._command_repo, "list_by_batch", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = commands

            result = await command_bus.list_batch_commands("payments", batch_id)

            assert result == commands
            mock_list.assert_called_once_with(
                domain="payments", batch_id=batch_id, status=None, limit=100, offset=0
            )

    @pytest.mark.asyncio
    async def test_list_batch_commands_filter(self, command_bus: CommandBus) -> None:
        """Test list_batch_commands with status filter."""
        batch_id = uuid4()
        now = datetime.now(UTC)
        commands = [
            CommandMetadata(
                domain="payments",
                command_id=uuid4(),
                command_type="DebitAccount",
                status=CommandStatus.COMPLETED,
                batch_id=batch_id,
                created_at=now,
                updated_at=now,
            ),
        ]

        with patch.object(
            command_bus._command_repo, "list_by_batch", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = commands

            result = await command_bus.list_batch_commands(
                "payments", batch_id, status=CommandStatus.COMPLETED
            )

            assert result == commands
            mock_list.assert_called_once_with(
                domain="payments",
                batch_id=batch_id,
                status=CommandStatus.COMPLETED,
                limit=100,
                offset=0,
            )

    @pytest.mark.asyncio
    async def test_list_batch_commands_empty(self, command_bus: CommandBus) -> None:
        """Test list_batch_commands returns empty list for non-existent batch."""
        with patch.object(
            command_bus._command_repo, "list_by_batch", new_callable=AsyncMock
        ) as mock_list:
            mock_list.return_value = []

            result = await command_bus.list_batch_commands("payments", uuid4())

            assert result == []


class TestCommandBusSendWithBatchId:
    """Tests for S044: Send with batch_id validation."""

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
    async def test_send_with_nonexistent_batch_raises_error(self, command_bus: CommandBus) -> None:
        """Test send with non-existent batch_id raises BatchNotFoundError."""
        batch_id = uuid4()
        command_id = uuid4()

        with (
            patch.object(command_bus._batch_repo, "exists", new_callable=AsyncMock) as mock_exists,
        ):
            mock_exists.return_value = False

            with pytest.raises(BatchNotFoundError) as exc_info:
                await command_bus.send(
                    domain="payments",
                    command_type="DebitAccount",
                    command_id=command_id,
                    data={"amount": 100},
                    batch_id=batch_id,
                )

            assert str(batch_id) in str(exc_info.value)
            assert "payments" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_with_valid_batch_succeeds(self, command_bus: CommandBus) -> None:
        """Test send with valid batch_id succeeds."""
        batch_id = uuid4()
        command_id = uuid4()

        with (
            patch.object(
                command_bus._batch_repo, "exists", new_callable=AsyncMock
            ) as mock_batch_exists,
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_cmd_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock) as mock_save,
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_batch_exists.return_value = True
            mock_cmd_exists.return_value = False
            mock_send.return_value = 123

            result = await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"amount": 100},
                batch_id=batch_id,
            )

            assert result.command_id == command_id
            assert result.msg_id == 123
            mock_batch_exists.assert_called_once()
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_without_batch_id_skips_validation(self, command_bus: CommandBus) -> None:
        """Test send without batch_id does not validate batch."""
        command_id = uuid4()

        with (
            patch.object(
                command_bus._batch_repo, "exists", new_callable=AsyncMock
            ) as mock_batch_exists,
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_cmd_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_cmd_exists.return_value = False
            mock_send.return_value = 123

            await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"amount": 100},
            )

            mock_batch_exists.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_with_batch_includes_batch_id_in_metadata(
        self, command_bus: CommandBus
    ) -> None:
        """Test send with batch_id stores batch_id in command metadata."""
        batch_id = uuid4()
        command_id = uuid4()
        saved_metadata: CommandMetadata | None = None

        async def capture_metadata(
            metadata: CommandMetadata, queue_name: str, conn: MagicMock
        ) -> None:
            nonlocal saved_metadata
            saved_metadata = metadata

        with (
            patch.object(
                command_bus._batch_repo, "exists", new_callable=AsyncMock
            ) as mock_batch_exists,
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_cmd_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_send,
            patch.object(command_bus._command_repo, "save", side_effect=capture_metadata),
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_batch_exists.return_value = True
            mock_cmd_exists.return_value = False
            mock_send.return_value = 123

            await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"amount": 100},
                batch_id=batch_id,
            )

            assert saved_metadata is not None
            assert saved_metadata.batch_id == batch_id
