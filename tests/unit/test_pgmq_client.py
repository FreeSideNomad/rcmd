"""Unit tests for PgmqClient."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from commandbus.pgmq.client import PgmqClient, PgmqMessage


class TestPgmqMessage:
    """Tests for PgmqMessage dataclass."""

    def test_pgmq_message_creation(self) -> None:
        """Test creating a PgmqMessage."""
        msg = PgmqMessage(
            msg_id=123,
            read_count=1,
            enqueued_at="2024-01-01T00:00:00",
            vt="2024-01-01T00:00:30",
            message={"key": "value"},
        )

        assert msg.msg_id == 123
        assert msg.read_count == 1
        assert msg.message == {"key": "value"}


class TestPgmqClientCreateQueue:
    """Tests for PgmqClient.create_queue()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def mock_connection():
            yield conn

        pool.connection = mock_connection
        pool._mock_conn = conn
        return pool

    @pytest.fixture
    def client(self, mock_pool: MagicMock) -> PgmqClient:
        """Create a PgmqClient with mocked pool."""
        return PgmqClient(mock_pool)

    @pytest.mark.asyncio
    async def test_create_queue(self, client: PgmqClient, mock_pool: MagicMock) -> None:
        """Test creating a queue."""
        await client.create_queue("test_queue")

        mock_pool._mock_conn.execute.assert_called_once()
        call_args = mock_pool._mock_conn.execute.call_args
        assert "pgmq.create" in call_args[0][0]
        assert call_args[0][1] == ("test_queue",)


class TestPgmqClientSend:
    """Tests for PgmqClient.send()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(42,))

        @asynccontextmanager
        async def mock_cursor():
            yield cursor

        conn.cursor = mock_cursor

        @asynccontextmanager
        async def mock_connection():
            yield conn

        pool.connection = mock_connection
        pool._mock_conn = conn
        pool._mock_cursor = cursor
        return pool

    @pytest.fixture
    def client(self, mock_pool: MagicMock) -> PgmqClient:
        """Create a PgmqClient with mocked pool."""
        return PgmqClient(mock_pool)

    @pytest.mark.asyncio
    async def test_send_without_conn(
        self, client: PgmqClient, mock_pool: MagicMock
    ) -> None:
        """Test sending a message using pool connection."""
        result = await client.send("test_queue", {"key": "value"})

        assert result == 42
        mock_pool._mock_cursor.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_with_external_conn(self, client: PgmqClient) -> None:
        """Test sending a message with an external connection."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(99,))

        @asynccontextmanager
        async def mock_cursor():
            yield cursor

        conn.cursor = mock_cursor

        result = await client.send("test_queue", {"key": "value"}, conn=conn)

        assert result == 99

    @pytest.mark.asyncio
    async def test_send_with_delay(
        self, client: PgmqClient, mock_pool: MagicMock
    ) -> None:
        """Test sending a message with delay."""
        await client.send("test_queue", {"key": "value"}, delay=10)

        call_args = mock_pool._mock_cursor.execute.call_args
        assert call_args[0][1][2] == 10  # delay parameter

    @pytest.mark.asyncio
    async def test_send_failure_raises_error(self, client: PgmqClient) -> None:
        """Test that send raises error when no result returned."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=None)

        @asynccontextmanager
        async def mock_cursor():
            yield cursor

        conn.cursor = mock_cursor

        with pytest.raises(RuntimeError, match="Failed to send message"):
            await client.send("test_queue", {"key": "value"}, conn=conn)


class TestPgmqClientRead:
    """Tests for PgmqClient.read()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        cursor.fetchall = AsyncMock(
            return_value=[
                (1, 0, "2024-01-01", "2024-01-01", '{"key": "value"}'),
            ]
        )

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
    def client(self, mock_pool: MagicMock) -> PgmqClient:
        """Create a PgmqClient with mocked pool."""
        return PgmqClient(mock_pool)

    @pytest.mark.asyncio
    async def test_read_returns_messages(
        self, client: PgmqClient, mock_pool: MagicMock
    ) -> None:
        """Test reading messages from queue."""
        messages = await client.read("test_queue")

        assert len(messages) == 1
        assert messages[0].msg_id == 1
        assert messages[0].message == {"key": "value"}

    @pytest.mark.asyncio
    async def test_read_with_dict_message(self, client: PgmqClient) -> None:
        """Test reading when message is already a dict."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        cursor.fetchall = AsyncMock(
            return_value=[
                (1, 0, "2024-01-01", "2024-01-01", {"key": "value"}),
            ]
        )

        @asynccontextmanager
        async def mock_cursor():
            yield cursor

        conn.cursor = mock_cursor

        @asynccontextmanager
        async def mock_connection():
            yield conn

        pool = MagicMock()
        pool.connection = mock_connection

        client = PgmqClient(pool)
        messages = await client.read("test_queue")

        assert messages[0].message == {"key": "value"}

    @pytest.mark.asyncio
    async def test_read_empty_queue(self, client: PgmqClient, mock_pool: MagicMock) -> None:
        """Test reading from empty queue."""
        mock_pool._mock_cursor.fetchall = AsyncMock(return_value=[])

        messages = await client.read("test_queue")

        assert messages == []


class TestPgmqClientDelete:
    """Tests for PgmqClient.delete()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

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
    def client(self, mock_pool: MagicMock) -> PgmqClient:
        """Create a PgmqClient with mocked pool."""
        return PgmqClient(mock_pool)

    @pytest.mark.asyncio
    async def test_delete_returns_true(
        self, client: PgmqClient, mock_pool: MagicMock
    ) -> None:
        """Test deleting a message."""
        result = await client.delete("test_queue", 1)

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_not_found(
        self, client: PgmqClient, mock_pool: MagicMock
    ) -> None:
        """Test delete when message not found."""
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=(False,))

        result = await client.delete("test_queue", 999)

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_no_row(
        self, client: PgmqClient, mock_pool: MagicMock
    ) -> None:
        """Test delete when no row returned."""
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=None)

        result = await client.delete("test_queue", 999)

        assert result is False


class TestPgmqClientArchive:
    """Tests for PgmqClient.archive()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(True,))

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
    def client(self, mock_pool: MagicMock) -> PgmqClient:
        """Create a PgmqClient with mocked pool."""
        return PgmqClient(mock_pool)

    @pytest.mark.asyncio
    async def test_archive_returns_true(
        self, client: PgmqClient, mock_pool: MagicMock
    ) -> None:
        """Test archiving a message."""
        result = await client.archive("test_queue", 1)

        assert result is True

    @pytest.mark.asyncio
    async def test_archive_no_row(
        self, client: PgmqClient, mock_pool: MagicMock
    ) -> None:
        """Test archive when no row returned."""
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=None)

        result = await client.archive("test_queue", 999)

        assert result is False


class TestPgmqClientSetVt:
    """Tests for PgmqClient.set_vt()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(1, "2024-01-01"))

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
    def client(self, mock_pool: MagicMock) -> PgmqClient:
        """Create a PgmqClient with mocked pool."""
        return PgmqClient(mock_pool)

    @pytest.mark.asyncio
    async def test_set_vt_returns_true(
        self, client: PgmqClient, mock_pool: MagicMock
    ) -> None:
        """Test setting visibility timeout."""
        result = await client.set_vt("test_queue", 1, 60)

        assert result is True

    @pytest.mark.asyncio
    async def test_set_vt_not_found(
        self, client: PgmqClient, mock_pool: MagicMock
    ) -> None:
        """Test set_vt when message not found."""
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=None)

        result = await client.set_vt("test_queue", 999, 60)

        assert result is False
