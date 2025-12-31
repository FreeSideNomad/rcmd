"""Unit tests for TroubleshootingQueue operations."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from commandbus.exceptions import CommandNotFoundError, InvalidOperationError
from commandbus.models import CommandMetadata, CommandStatus
from commandbus.ops.troubleshooting import TroubleshootingQueue


class TestTroubleshootingQueueListTroubleshooting:
    """Tests for TroubleshootingQueue.list_troubleshooting()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with cursor."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()

        cursor.execute = AsyncMock()
        cursor.fetchall = AsyncMock(return_value=[])

        @asynccontextmanager
        async def mock_cursor():
            yield cursor

        conn.cursor = mock_cursor

        @asynccontextmanager
        async def mock_connection():
            yield conn

        pool.connection = mock_connection
        pool._mock_cursor = cursor
        return pool

    @pytest.fixture
    def tsq(self, mock_pool: MagicMock) -> TroubleshootingQueue:
        """Create a TroubleshootingQueue with mocked pool."""
        return TroubleshootingQueue(mock_pool)

    @pytest.mark.asyncio
    async def test_list_empty_returns_empty_list(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test listing when no items in troubleshooting queue."""
        items = await tsq.list_troubleshooting("payments")

        assert items == []
        mock_pool._mock_cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_returns_items(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test listing returns TroubleshootingItem objects."""
        command_id = uuid4()
        correlation_id = uuid4()
        now = datetime.now(UTC)

        mock_pool._mock_cursor.fetchall = AsyncMock(
            return_value=[
                (
                    "payments",  # domain
                    command_id,  # command_id
                    "DebitAccount",  # command_type
                    3,  # attempts
                    3,  # max_attempts
                    "PERMANENT",  # last_error_type
                    "INVALID_ACCOUNT",  # last_error_code
                    "Account not found",  # last_error_msg
                    correlation_id,  # correlation_id
                    "reply_queue",  # reply_queue
                    {"amount": 100},  # message (payload as dict)
                    now,  # created_at
                    now,  # updated_at
                ),
            ]
        )

        items = await tsq.list_troubleshooting("payments")

        assert len(items) == 1
        item = items[0]
        assert item.domain == "payments"
        assert item.command_id == command_id
        assert item.command_type == "DebitAccount"
        assert item.attempts == 3
        assert item.max_attempts == 3
        assert item.last_error_type == "PERMANENT"
        assert item.last_error_code == "INVALID_ACCOUNT"
        assert item.last_error_msg == "Account not found"
        assert item.correlation_id == correlation_id
        assert item.reply_to == "reply_queue"
        assert item.payload == {"amount": 100}
        assert item.created_at == now
        assert item.updated_at == now

    @pytest.mark.asyncio
    async def test_list_parses_json_string_payload(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test listing parses JSON string payload from archive."""
        command_id = uuid4()
        now = datetime.now(UTC)

        mock_pool._mock_cursor.fetchall = AsyncMock(
            return_value=[
                (
                    "payments",
                    command_id,
                    "DebitAccount",
                    2,
                    3,
                    "TRANSIENT",
                    "TIMEOUT",
                    "Service timeout",
                    None,
                    None,
                    '{"amount": 200}',  # JSON string payload
                    now,
                    now,
                ),
            ]
        )

        items = await tsq.list_troubleshooting("payments")

        assert len(items) == 1
        assert items[0].payload == {"amount": 200}

    @pytest.mark.asyncio
    async def test_list_handles_null_payload(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test listing handles null payload (archive message missing)."""
        command_id = uuid4()
        now = datetime.now(UTC)

        mock_pool._mock_cursor.fetchall = AsyncMock(
            return_value=[
                (
                    "payments",
                    command_id,
                    "DebitAccount",
                    2,
                    3,
                    "TRANSIENT",
                    "TIMEOUT",
                    "Service timeout",
                    None,
                    None,
                    None,  # No archived message
                    now,
                    now,
                ),
            ]
        )

        items = await tsq.list_troubleshooting("payments")

        assert len(items) == 1
        assert items[0].payload is None

    @pytest.mark.asyncio
    async def test_list_handles_null_reply_queue(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test listing handles null reply queue."""
        command_id = uuid4()
        now = datetime.now(UTC)

        mock_pool._mock_cursor.fetchall = AsyncMock(
            return_value=[
                (
                    "payments",
                    command_id,
                    "DebitAccount",
                    2,
                    3,
                    None,
                    None,
                    None,
                    None,
                    "",  # Empty string reply queue
                    None,
                    now,
                    now,
                ),
            ]
        )

        items = await tsq.list_troubleshooting("payments")

        assert len(items) == 1
        assert items[0].reply_to is None

    @pytest.mark.asyncio
    async def test_list_with_command_type_filter(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test listing with command_type filter adds parameter."""
        await tsq.list_troubleshooting("payments", command_type="DebitAccount")

        call_args = mock_pool._mock_cursor.execute.call_args
        params = call_args[0][1]
        assert len(params) == 5  # domain, status, command_type, limit, offset
        assert params[0] == "payments"
        assert params[1] == CommandStatus.IN_TROUBLESHOOTING_QUEUE.value
        assert params[2] == "DebitAccount"
        assert params[3] == 50  # default limit
        assert params[4] == 0  # default offset

    @pytest.mark.asyncio
    async def test_list_with_pagination(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test listing with custom limit and offset."""
        await tsq.list_troubleshooting("payments", limit=10, offset=20)

        call_args = mock_pool._mock_cursor.execute.call_args
        params = call_args[0][1]
        # domain, status, limit, offset (no command_type)
        assert params[-2] == 10  # limit
        assert params[-1] == 20  # offset

    @pytest.mark.asyncio
    async def test_list_multiple_items(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test listing returns multiple items."""
        now = datetime.now(UTC)

        mock_pool._mock_cursor.fetchall = AsyncMock(
            return_value=[
                (
                    "payments",
                    uuid4(),
                    "DebitAccount",
                    3,
                    3,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
                (
                    "payments",
                    uuid4(),
                    "CreditAccount",
                    2,
                    3,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
                (
                    "payments",
                    uuid4(),
                    "TransferFunds",
                    1,
                    3,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    now,
                    now,
                ),
            ]
        )

        items = await tsq.list_troubleshooting("payments")

        assert len(items) == 3
        assert items[0].command_type == "DebitAccount"
        assert items[1].command_type == "CreditAccount"
        assert items[2].command_type == "TransferFunds"


class TestTroubleshootingQueueCountTroubleshooting:
    """Tests for TroubleshootingQueue.count_troubleshooting()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with cursor."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()

        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(0,))

        @asynccontextmanager
        async def mock_cursor():
            yield cursor

        conn.cursor = mock_cursor

        @asynccontextmanager
        async def mock_connection():
            yield conn

        pool.connection = mock_connection
        pool._mock_cursor = cursor
        return pool

    @pytest.fixture
    def tsq(self, mock_pool: MagicMock) -> TroubleshootingQueue:
        """Create a TroubleshootingQueue with mocked pool."""
        return TroubleshootingQueue(mock_pool)

    @pytest.mark.asyncio
    async def test_count_returns_zero_when_empty(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test count returns 0 when no items."""
        count = await tsq.count_troubleshooting("payments")

        assert count == 0
        mock_pool._mock_cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_count_returns_count(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test count returns correct number."""
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=(42,))

        count = await tsq.count_troubleshooting("payments")

        assert count == 42

    @pytest.mark.asyncio
    async def test_count_with_command_type_filter(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test count with command_type filter adds parameter."""
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=(5,))

        count = await tsq.count_troubleshooting("payments", command_type="DebitAccount")

        assert count == 5
        call_args = mock_pool._mock_cursor.execute.call_args
        params = call_args[0][1]
        assert len(params) == 3  # domain, status, command_type
        assert params[2] == "DebitAccount"

    @pytest.mark.asyncio
    async def test_count_handles_null_row(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test count returns 0 when fetchone returns None."""
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=None)

        count = await tsq.count_troubleshooting("payments")

        assert count == 0


class TestTroubleshootingQueueOperatorRetry:
    """Tests for TroubleshootingQueue.operator_retry()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with cursor and transaction support."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()

        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=None)

        @asynccontextmanager
        async def mock_cursor():
            yield cursor

        conn.cursor = mock_cursor
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def mock_transaction():
            yield

        conn.transaction = mock_transaction

        @asynccontextmanager
        async def mock_connection():
            yield conn

        pool.connection = mock_connection
        pool._mock_cursor = cursor
        pool._mock_conn = conn
        return pool

    @pytest.fixture
    def tsq(self, mock_pool: MagicMock) -> TroubleshootingQueue:
        """Create a TroubleshootingQueue with mocked pool."""
        return TroubleshootingQueue(mock_pool)

    @pytest.mark.asyncio
    async def test_raises_command_not_found_when_missing(self, tsq: TroubleshootingQueue) -> None:
        """Test raises CommandNotFoundError when command doesn't exist."""
        command_id = uuid4()

        with patch("commandbus.ops.troubleshooting.PostgresCommandRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get = AsyncMock(return_value=None)
            mock_repo_class.return_value = mock_repo

            with pytest.raises(CommandNotFoundError) as exc_info:
                await tsq.operator_retry("payments", command_id)

            assert exc_info.value.domain == "payments"
            assert exc_info.value.command_id == str(command_id)

    @pytest.mark.asyncio
    async def test_raises_invalid_operation_when_not_in_tsq(
        self, tsq: TroubleshootingQueue
    ) -> None:
        """Test raises InvalidOperationError when command not in TSQ."""
        command_id = uuid4()
        now = datetime.now(UTC)

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.PENDING,  # Not in TSQ
            attempts=0,
            max_attempts=3,
            msg_id=1,
            correlation_id=None,
            reply_to=None,
            created_at=now,
            updated_at=now,
        )

        with patch("commandbus.ops.troubleshooting.PostgresCommandRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get = AsyncMock(return_value=metadata)
            mock_repo_class.return_value = mock_repo

            with pytest.raises(InvalidOperationError) as exc_info:
                await tsq.operator_retry("payments", command_id)

            assert "not in troubleshooting queue" in str(exc_info.value)
            assert "PENDING" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_invalid_operation_when_payload_not_found(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test raises InvalidOperationError when payload not in archive."""
        command_id = uuid4()
        now = datetime.now(UTC)

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.IN_TROUBLESHOOTING_QUEUE,
            attempts=3,
            max_attempts=3,
            msg_id=1,
            correlation_id=None,
            reply_to=None,
            created_at=now,
            updated_at=now,
        )

        # Cursor returns None for payload query
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=None)

        with patch("commandbus.ops.troubleshooting.PostgresCommandRepository") as mock_repo_class:
            mock_repo = MagicMock()
            mock_repo.get = AsyncMock(return_value=metadata)
            mock_repo_class.return_value = mock_repo

            with pytest.raises(InvalidOperationError) as exc_info:
                await tsq.operator_retry("payments", command_id)

            assert "Payload not found in archive" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_successful_retry_returns_new_msg_id(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test successful retry returns new message ID."""
        command_id = uuid4()
        now = datetime.now(UTC)
        payload = {"command_id": str(command_id), "data": {"amount": 100}}

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.IN_TROUBLESHOOTING_QUEUE,
            attempts=3,
            max_attempts=3,
            msg_id=1,
            correlation_id=None,
            reply_to=None,
            created_at=now,
            updated_at=now,
        )

        # Cursor returns payload
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=(payload,))

        with (
            patch("commandbus.ops.troubleshooting.PostgresCommandRepository") as mock_repo_class,
            patch("commandbus.ops.troubleshooting.PgmqClient") as mock_pgmq_class,
            patch("commandbus.ops.troubleshooting.PostgresAuditLogger") as mock_audit_class,
        ):
            mock_repo = MagicMock()
            mock_repo.get = AsyncMock(return_value=metadata)
            mock_repo_class.return_value = mock_repo

            mock_pgmq = MagicMock()
            mock_pgmq.send = AsyncMock(return_value=42)
            mock_pgmq_class.return_value = mock_pgmq

            mock_audit = MagicMock()
            mock_audit.log = AsyncMock()
            mock_audit_class.return_value = mock_audit

            result = await tsq.operator_retry("payments", command_id, operator="admin")

            assert result == 42
            mock_pgmq.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_command_metadata(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test retry updates command metadata correctly."""
        command_id = uuid4()
        now = datetime.now(UTC)
        payload = {"command_id": str(command_id), "data": {"amount": 100}}

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.IN_TROUBLESHOOTING_QUEUE,
            attempts=3,
            max_attempts=3,
            msg_id=1,
            correlation_id=None,
            reply_to=None,
            created_at=now,
            updated_at=now,
        )

        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=(payload,))

        with (
            patch("commandbus.ops.troubleshooting.PostgresCommandRepository") as mock_repo_class,
            patch("commandbus.ops.troubleshooting.PgmqClient") as mock_pgmq_class,
            patch("commandbus.ops.troubleshooting.PostgresAuditLogger") as mock_audit_class,
        ):
            mock_repo = MagicMock()
            mock_repo.get = AsyncMock(return_value=metadata)
            mock_repo_class.return_value = mock_repo

            mock_pgmq = MagicMock()
            mock_pgmq.send = AsyncMock(return_value=42)
            mock_pgmq_class.return_value = mock_pgmq

            mock_audit = MagicMock()
            mock_audit.log = AsyncMock()
            mock_audit_class.return_value = mock_audit

            await tsq.operator_retry("payments", command_id)

            # Verify UPDATE was called on the connection
            mock_pool._mock_conn.execute.assert_called()
            call_args = mock_pool._mock_conn.execute.call_args
            query = call_args[0][0]
            params = call_args[0][1]

            assert "UPDATE command_bus_command" in query
            assert "status = %s" in query
            assert "attempts = 0" in query
            assert CommandStatus.PENDING.value in params
            assert 42 in params  # new_msg_id

    @pytest.mark.asyncio
    async def test_records_audit_event(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test retry records OPERATOR_RETRY audit event."""
        command_id = uuid4()
        now = datetime.now(UTC)
        payload = {"command_id": str(command_id), "data": {"amount": 100}}

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.IN_TROUBLESHOOTING_QUEUE,
            attempts=3,
            max_attempts=3,
            msg_id=1,
            correlation_id=None,
            reply_to=None,
            created_at=now,
            updated_at=now,
        )

        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=(payload,))

        with (
            patch("commandbus.ops.troubleshooting.PostgresCommandRepository") as mock_repo_class,
            patch("commandbus.ops.troubleshooting.PgmqClient") as mock_pgmq_class,
            patch("commandbus.ops.troubleshooting.PostgresAuditLogger") as mock_audit_class,
        ):
            mock_repo = MagicMock()
            mock_repo.get = AsyncMock(return_value=metadata)
            mock_repo_class.return_value = mock_repo

            mock_pgmq = MagicMock()
            mock_pgmq.send = AsyncMock(return_value=42)
            mock_pgmq_class.return_value = mock_pgmq

            mock_audit = MagicMock()
            mock_audit.log = AsyncMock()
            mock_audit_class.return_value = mock_audit

            await tsq.operator_retry("payments", command_id, operator="admin_user")

            mock_audit.log.assert_called_once()
            call_kwargs = mock_audit.log.call_args[1]
            assert call_kwargs["domain"] == "payments"
            assert call_kwargs["command_id"] == command_id
            assert call_kwargs["event_type"].value == "OPERATOR_RETRY"
            assert call_kwargs["details"]["operator"] == "admin_user"
            assert call_kwargs["details"]["new_msg_id"] == 42

    @pytest.mark.asyncio
    async def test_parses_json_string_payload(
        self, tsq: TroubleshootingQueue, mock_pool: MagicMock
    ) -> None:
        """Test retry parses JSON string payload from archive."""
        command_id = uuid4()
        now = datetime.now(UTC)
        payload_str = '{"command_id": "test", "data": {"amount": 100}}'

        metadata = CommandMetadata(
            domain="payments",
            command_id=command_id,
            command_type="DebitAccount",
            status=CommandStatus.IN_TROUBLESHOOTING_QUEUE,
            attempts=3,
            max_attempts=3,
            msg_id=1,
            correlation_id=None,
            reply_to=None,
            created_at=now,
            updated_at=now,
        )

        # Return JSON string instead of dict
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=(payload_str,))

        with (
            patch("commandbus.ops.troubleshooting.PostgresCommandRepository") as mock_repo_class,
            patch("commandbus.ops.troubleshooting.PgmqClient") as mock_pgmq_class,
            patch("commandbus.ops.troubleshooting.PostgresAuditLogger") as mock_audit_class,
        ):
            mock_repo = MagicMock()
            mock_repo.get = AsyncMock(return_value=metadata)
            mock_repo_class.return_value = mock_repo

            mock_pgmq = MagicMock()
            mock_pgmq.send = AsyncMock(return_value=42)
            mock_pgmq_class.return_value = mock_pgmq

            mock_audit = MagicMock()
            mock_audit.log = AsyncMock()
            mock_audit_class.return_value = mock_audit

            result = await tsq.operator_retry("payments", command_id)

            assert result == 42
            # Verify payload was parsed and sent
            mock_pgmq.send.assert_called_once()
            sent_payload = mock_pgmq.send.call_args[0][1]
            assert sent_payload == {"command_id": "test", "data": {"amount": 100}}
