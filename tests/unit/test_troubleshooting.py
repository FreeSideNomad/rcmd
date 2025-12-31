"""Unit tests for TroubleshootingQueue operations."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from commandbus.models import CommandStatus
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
