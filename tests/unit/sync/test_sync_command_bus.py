"""Unit tests for commandbus.sync.bus module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from commandbus.batch import (
    clear_all_callbacks,
    get_sync_batch_callback,
    invoke_sync_batch_callback,
    register_batch_callback_sync,
    remove_sync_batch_callback,
)
from commandbus.exceptions import BatchNotFoundError, DuplicateCommandError
from commandbus.models import (
    BatchCommand,
    BatchMetadata,
    BatchSendResult,
    BatchStatus,
    CommandMetadata,
    CommandStatus,
    CreateBatchResult,
    SendRequest,
    SendResult,
)
from commandbus.sync.bus import (
    DEFAULT_BATCH_CHUNK_SIZE,
    SyncCommandBus,
    _chunked,
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


class TestChunked:
    """Tests for _chunked helper function."""

    def test_empty_list(self) -> None:
        """Should return empty list for empty input."""
        result = _chunked([], 10)
        assert result == []

    def test_single_chunk(self) -> None:
        """Should return single chunk when items < size."""
        result = _chunked([1, 2, 3], 10)
        assert result == [[1, 2, 3]]

    def test_exact_chunks(self) -> None:
        """Should split into exact chunks."""
        result = _chunked([1, 2, 3, 4], 2)
        assert result == [[1, 2], [3, 4]]

    def test_partial_last_chunk(self) -> None:
        """Should handle partial last chunk."""
        result = _chunked([1, 2, 3, 4, 5], 2)
        assert result == [[1, 2], [3, 4], [5]]


class TestSyncCommandBusInit:
    """Tests for SyncCommandBus initialization."""

    def test_init_with_defaults(self) -> None:
        """Should initialize with default max_attempts."""
        mock_pool = MagicMock()
        bus = SyncCommandBus(mock_pool)

        assert bus._pool is mock_pool
        assert bus._default_max_attempts == 3
        assert bus._pgmq is not None
        assert bus._command_repo is not None
        assert bus._batch_repo is not None
        assert bus._audit_logger is not None

    def test_init_with_custom_max_attempts(self) -> None:
        """Should allow custom default_max_attempts."""
        mock_pool = MagicMock()
        bus = SyncCommandBus(mock_pool, default_max_attempts=5)

        assert bus._default_max_attempts == 5


class TestSyncCommandBusSend:
    """Tests for SyncCommandBus.send method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.bus = SyncCommandBus(self.mock_pool)

        # Mock the internal components
        self.bus._pgmq = MagicMock()
        self.bus._command_repo = MagicMock()
        self.bus._batch_repo = MagicMock()
        self.bus._audit_logger = MagicMock()

        # Default mock returns
        self.bus._pgmq.send.return_value = 123
        self.bus._command_repo.exists.return_value = False

    def test_send_basic_command(self) -> None:
        """Should send a basic command successfully."""
        command_id = uuid4()

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        result = self.bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"amount": 100},
        )

        assert isinstance(result, SendResult)
        assert result.command_id == command_id
        assert result.msg_id == 123

        # Verify PGMQ send was called
        self.bus._pgmq.send.assert_called_once()
        call_args = self.bus._pgmq.send.call_args
        assert call_args[0][0] == "payments__commands"

        # Verify metadata was saved
        self.bus._command_repo.save.assert_called_once()

        # Verify audit event was logged
        self.bus._audit_logger.log.assert_called_once()

    def test_send_with_all_options(self) -> None:
        """Should send command with all optional parameters."""
        command_id = uuid4()
        correlation_id = uuid4()
        batch_id = uuid4()

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None
        self.bus._batch_repo.exists.return_value = True

        result = self.bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"amount": 100},
            correlation_id=correlation_id,
            reply_to="replies",
            max_attempts=5,
            batch_id=batch_id,
        )

        assert result.command_id == command_id

        # Verify batch existence was checked
        self.bus._batch_repo.exists.assert_called_once()

    def test_send_raises_duplicate_error(self) -> None:
        """Should raise DuplicateCommandError if command exists."""
        command_id = uuid4()
        self.bus._command_repo.exists.return_value = True

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        with pytest.raises(DuplicateCommandError):
            self.bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"amount": 100},
            )

    def test_send_raises_batch_not_found(self) -> None:
        """Should raise BatchNotFoundError if batch doesn't exist."""
        command_id = uuid4()
        batch_id = uuid4()
        self.bus._batch_repo.exists.return_value = False

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        with pytest.raises(BatchNotFoundError):
            self.bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"amount": 100},
                batch_id=batch_id,
            )

    def test_send_with_external_connection(self) -> None:
        """Should use provided connection instead of pool."""
        command_id = uuid4()
        external_conn = MagicMock()

        result = self.bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"amount": 100},
            conn=external_conn,
        )

        assert result.command_id == command_id
        # Pool should not be used
        self.mock_pool.connection.assert_not_called()

    def test_send_generates_correlation_id(self) -> None:
        """Should auto-generate correlation_id if not provided."""
        command_id = uuid4()

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        self.bus.send(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"amount": 100},
        )

        # Verify audit log contains correlation_id
        call_kwargs = self.bus._audit_logger.log.call_args[1]
        assert "correlation_id" in call_kwargs["details"]


class TestSyncCommandBusSendBatch:
    """Tests for SyncCommandBus.send_batch method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.bus = SyncCommandBus(self.mock_pool)

        self.bus._pgmq = MagicMock()
        self.bus._command_repo = MagicMock()
        self.bus._batch_repo = MagicMock()
        self.bus._audit_logger = MagicMock()

        self.bus._command_repo.exists_batch.return_value = set()

    def test_send_batch_empty_list(self) -> None:
        """Should return empty result for empty requests."""
        result = self.bus.send_batch([])

        assert isinstance(result, BatchSendResult)
        assert result.results == []
        assert result.chunks_processed == 0
        assert result.total_commands == 0

    def test_send_batch_single_request(self) -> None:
        """Should send single command in batch."""
        command_id = uuid4()
        requests = [
            SendRequest(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"amount": 100},
            )
        ]

        self.bus._pgmq.send_batch.return_value = [123]

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        result = self.bus.send_batch(requests)

        assert result.total_commands == 1
        assert result.chunks_processed == 1
        assert len(result.results) == 1
        assert result.results[0].command_id == command_id

    def test_send_batch_multiple_domains(self) -> None:
        """Should handle requests from multiple domains."""
        requests = [
            SendRequest(
                domain="payments",
                command_type="Debit",
                command_id=uuid4(),
                data={"amount": 100},
            ),
            SendRequest(
                domain="orders",
                command_type="Create",
                command_id=uuid4(),
                data={"item": "widget"},
            ),
        ]

        self.bus._pgmq.send_batch.return_value = [123]

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        result = self.bus.send_batch(requests)

        assert result.total_commands == 2
        # Should call send_batch once per domain
        assert self.bus._pgmq.send_batch.call_count == 2

    def test_send_batch_raises_duplicate_error(self) -> None:
        """Should raise DuplicateCommandError on duplicates."""
        command_id = uuid4()
        requests = [
            SendRequest(
                domain="payments",
                command_type="Debit",
                command_id=command_id,
                data={"amount": 100},
            ),
        ]

        self.bus._command_repo.exists_batch.return_value = {command_id}

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        with pytest.raises(DuplicateCommandError):
            self.bus.send_batch(requests)

    def test_send_batch_chunking(self) -> None:
        """Should process requests in chunks."""
        requests = [
            SendRequest(
                domain="payments",
                command_type="Debit",
                command_id=uuid4(),
                data={"amount": i},
            )
            for i in range(5)
        ]

        self.bus._pgmq.send_batch.return_value = [100 + i for i in range(2)]

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        result = self.bus.send_batch(requests, chunk_size=2)

        assert result.chunks_processed == 3  # 2 + 2 + 1


class TestSyncCommandBusGetCommand:
    """Tests for SyncCommandBus.get_command method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.bus = SyncCommandBus(self.mock_pool)
        self.bus._command_repo = MagicMock()

    def test_get_command_found(self) -> None:
        """Should return command metadata when found."""
        command_id = uuid4()
        expected = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="Debit",
            status=CommandStatus.PENDING,
            attempts=0,
            max_attempts=3,
            msg_id=123,
            correlation_id=uuid4(),
            reply_to=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.bus._command_repo.get.return_value = expected

        result = self.bus.get_command("payments", command_id)

        assert result == expected

    def test_get_command_not_found(self) -> None:
        """Should return None when not found."""
        self.bus._command_repo.get.return_value = None

        result = self.bus.get_command("payments", uuid4())

        assert result is None


class TestSyncCommandBusCommandExists:
    """Tests for SyncCommandBus.command_exists method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.bus = SyncCommandBus(self.mock_pool)
        self.bus._command_repo = MagicMock()

    def test_command_exists_true(self) -> None:
        """Should return True when command exists."""
        self.bus._command_repo.exists.return_value = True
        assert self.bus.command_exists("payments", uuid4()) is True

    def test_command_exists_false(self) -> None:
        """Should return False when command doesn't exist."""
        self.bus._command_repo.exists.return_value = False
        assert self.bus.command_exists("payments", uuid4()) is False


class TestSyncCommandBusGetAuditTrail:
    """Tests for SyncCommandBus.get_audit_trail method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.bus = SyncCommandBus(self.mock_pool)
        self.bus._audit_logger = MagicMock()

    def test_get_audit_trail(self) -> None:
        """Should return audit events."""
        command_id = uuid4()
        events = [MagicMock(), MagicMock()]
        self.bus._audit_logger.get_events.return_value = events

        result = self.bus.get_audit_trail(command_id, "payments")

        assert result == events
        self.bus._audit_logger.get_events.assert_called_with(command_id, "payments")


class TestSyncCommandBusCreateBatch:
    """Tests for SyncCommandBus.create_batch method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.bus = SyncCommandBus(self.mock_pool)

        self.bus._pgmq = MagicMock()
        self.bus._command_repo = MagicMock()
        self.bus._batch_repo = MagicMock()
        self.bus._audit_logger = MagicMock()

        self.bus._command_repo.exists_batch.return_value = set()
        self.bus._pgmq.send_batch.return_value = [123, 124]

        # Clear callbacks from previous tests
        clear_all_callbacks()

    def test_create_batch_empty_commands_raises(self) -> None:
        """Should raise ValueError for empty commands list."""
        with pytest.raises(ValueError, match="at least one command"):
            self.bus.create_batch(domain="payments", commands=[])

    def test_create_batch_success(self) -> None:
        """Should create batch with multiple commands."""
        commands = [
            BatchCommand(
                command_type="Debit",
                command_id=uuid4(),
                data={"amount": 100},
            ),
            BatchCommand(
                command_type="Debit",
                command_id=uuid4(),
                data={"amount": 200},
            ),
        ]

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        result = self.bus.create_batch(domain="payments", commands=commands)

        assert isinstance(result, CreateBatchResult)
        assert result.total_commands == 2
        assert len(result.command_results) == 2

        # Verify batch was saved
        self.bus._batch_repo.save.assert_called_once()

    def test_create_batch_with_callback(self) -> None:
        """Should register callback when provided."""
        command_id = uuid4()
        commands = [
            BatchCommand(
                command_type="Debit",
                command_id=command_id,
                data={"amount": 100},
            ),
        ]
        callback = MagicMock()

        self.bus._pgmq.send_batch.return_value = [123]

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        result = self.bus.create_batch(
            domain="payments",
            commands=commands,
            on_complete=callback,
        )

        # Verify callback was registered
        registered = get_sync_batch_callback("payments", result.batch_id)
        assert registered is callback

    def test_create_batch_duplicate_in_batch_raises(self) -> None:
        """Should raise DuplicateCommandError for duplicates within batch."""
        command_id = uuid4()
        commands = [
            BatchCommand(command_type="Debit", command_id=command_id, data={}),
            BatchCommand(command_type="Debit", command_id=command_id, data={}),
        ]

        with pytest.raises(DuplicateCommandError):
            self.bus.create_batch(domain="payments", commands=commands)

    def test_create_batch_duplicate_in_db_raises(self) -> None:
        """Should raise DuplicateCommandError for existing command in DB."""
        command_id = uuid4()
        commands = [
            BatchCommand(command_type="Debit", command_id=command_id, data={}),
        ]

        self.bus._command_repo.exists_batch.return_value = {command_id}

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        with pytest.raises(DuplicateCommandError):
            self.bus.create_batch(domain="payments", commands=commands)

    def test_create_batch_with_custom_batch_id(self) -> None:
        """Should use provided batch_id."""
        batch_id = uuid4()
        commands = [
            BatchCommand(command_type="Debit", command_id=uuid4(), data={}),
        ]

        self.bus._pgmq.send_batch.return_value = [123]

        mock_conn = MagicMock()
        self.mock_pool.connection.return_value.__enter__.return_value = mock_conn
        mock_conn.transaction.return_value.__enter__.return_value = None

        result = self.bus.create_batch(
            domain="payments",
            commands=commands,
            batch_id=batch_id,
        )

        assert result.batch_id == batch_id


class TestSyncCommandBusGetBatch:
    """Tests for SyncCommandBus.get_batch method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.bus = SyncCommandBus(self.mock_pool)
        self.bus._batch_repo = MagicMock()

    def test_get_batch_found(self) -> None:
        """Should return batch metadata when found."""
        batch_id = uuid4()
        expected = BatchMetadata(
            domain="payments",
            batch_id=batch_id,
            name="test",
            custom_data=None,
            status=BatchStatus.PENDING,
            total_count=10,
            completed_count=0,
            canceled_count=0,
            in_troubleshooting_count=0,
            created_at=datetime.now(UTC),
            started_at=None,
            completed_at=None,
        )
        self.bus._batch_repo.get.return_value = expected

        result = self.bus.get_batch("payments", batch_id)

        assert result == expected

    def test_get_batch_not_found(self) -> None:
        """Should return None when not found."""
        self.bus._batch_repo.get.return_value = None

        result = self.bus.get_batch("payments", uuid4())

        assert result is None


class TestSyncCommandBusListBatches:
    """Tests for SyncCommandBus.list_batches method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.bus = SyncCommandBus(self.mock_pool)
        self.bus._batch_repo = MagicMock()

    def test_list_batches_basic(self) -> None:
        """Should list batches for domain."""
        expected = [MagicMock(), MagicMock()]
        self.bus._batch_repo.list_batches.return_value = expected

        result = self.bus.list_batches("payments")

        assert result == expected
        self.bus._batch_repo.list_batches.assert_called_with(
            domain="payments",
            status=None,
            limit=100,
            offset=0,
        )

    def test_list_batches_with_filters(self) -> None:
        """Should pass filters to repository."""
        self.bus._batch_repo.list_batches.return_value = []

        self.bus.list_batches(
            "payments",
            status=BatchStatus.PENDING,
            limit=50,
            offset=10,
        )

        self.bus._batch_repo.list_batches.assert_called_with(
            domain="payments",
            status=BatchStatus.PENDING,
            limit=50,
            offset=10,
        )


class TestSyncCommandBusListBatchCommands:
    """Tests for SyncCommandBus.list_batch_commands method."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_pool = MagicMock()
        self.bus = SyncCommandBus(self.mock_pool)
        self.bus._command_repo = MagicMock()

    def test_list_batch_commands_basic(self) -> None:
        """Should list commands in batch."""
        batch_id = uuid4()
        expected = [MagicMock(), MagicMock()]
        self.bus._command_repo.list_by_batch.return_value = expected

        result = self.bus.list_batch_commands("payments", batch_id)

        assert result == expected
        self.bus._command_repo.list_by_batch.assert_called_with(
            domain="payments",
            batch_id=batch_id,
            status=None,
            limit=100,
            offset=0,
        )

    def test_list_batch_commands_with_filters(self) -> None:
        """Should pass filters to repository."""
        batch_id = uuid4()
        self.bus._command_repo.list_by_batch.return_value = []

        self.bus.list_batch_commands(
            "payments",
            batch_id,
            status=CommandStatus.COMPLETED,
            limit=50,
            offset=10,
        )

        self.bus._command_repo.list_by_batch.assert_called_with(
            domain="payments",
            batch_id=batch_id,
            status=CommandStatus.COMPLETED,
            limit=50,
            offset=10,
        )


class TestSyncBatchCallbacks:
    """Tests for sync batch callback functions."""

    def setup_method(self) -> None:
        """Clear callbacks before each test."""
        clear_all_callbacks()

    def test_register_and_get_sync_callback(self) -> None:
        """Should register and retrieve sync callback."""
        batch_id = uuid4()
        callback = MagicMock()

        register_batch_callback_sync("payments", batch_id, callback)

        retrieved = get_sync_batch_callback("payments", batch_id)
        assert retrieved is callback

    def test_remove_sync_callback(self) -> None:
        """Should remove sync callback."""
        batch_id = uuid4()
        callback = MagicMock()

        register_batch_callback_sync("payments", batch_id, callback)
        remove_sync_batch_callback("payments", batch_id)

        retrieved = get_sync_batch_callback("payments", batch_id)
        assert retrieved is None

    def test_invoke_sync_batch_callback(self) -> None:
        """Should invoke sync callback with batch metadata."""
        batch_id = uuid4()
        callback = MagicMock()

        register_batch_callback_sync("payments", batch_id, callback)

        # Create mock batch repo
        mock_batch_repo = MagicMock()
        batch_metadata = BatchMetadata(
            domain="payments",
            batch_id=batch_id,
            name="test",
            custom_data=None,
            status=BatchStatus.COMPLETED,
            total_count=1,
            completed_count=1,
            canceled_count=0,
            in_troubleshooting_count=0,
            created_at=datetime.now(UTC),
            started_at=None,
            completed_at=datetime.now(UTC),
        )
        mock_batch_repo.get.return_value = batch_metadata

        invoke_sync_batch_callback("payments", batch_id, mock_batch_repo)

        callback.assert_called_once_with(batch_metadata)

    def test_invoke_sync_callback_handles_exception(self) -> None:
        """Should catch and log callback exceptions."""
        batch_id = uuid4()
        callback = MagicMock(side_effect=ValueError("callback error"))

        register_batch_callback_sync("payments", batch_id, callback)

        mock_batch_repo = MagicMock()
        mock_batch_repo.get.return_value = BatchMetadata(
            domain="payments",
            batch_id=batch_id,
            name="test",
            custom_data=None,
            status=BatchStatus.COMPLETED,
            total_count=1,
            completed_count=1,
            canceled_count=0,
            in_troubleshooting_count=0,
            created_at=datetime.now(UTC),
            started_at=None,
            completed_at=None,
        )

        # Should not raise
        invoke_sync_batch_callback("payments", batch_id, mock_batch_repo)

    def test_invoke_sync_callback_not_registered(self) -> None:
        """Should handle missing callback gracefully."""
        mock_batch_repo = MagicMock()

        # Should not raise
        invoke_sync_batch_callback("payments", uuid4(), mock_batch_repo)

        # Batch repo should not be called
        mock_batch_repo.get.assert_not_called()


class TestDefaultBatchChunkSize:
    """Tests for DEFAULT_BATCH_CHUNK_SIZE constant."""

    def test_chunk_size_value(self) -> None:
        """Should have expected default chunk size."""
        assert DEFAULT_BATCH_CHUNK_SIZE == 1_000
