"""Unit tests for repository implementations."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from commandbus.models import AuditEvent, CommandMetadata, CommandStatus
from commandbus.repositories.audit import AuditEventType, PostgresAuditLogger
from commandbus.repositories.command import PostgresCommandRepository


class TestPostgresCommandRepositorySave:
    """Tests for PostgresCommandRepository.save()."""

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
    def repo(self, mock_pool: MagicMock) -> PostgresCommandRepository:
        """Create a repository with mocked pool."""
        return PostgresCommandRepository(mock_pool)

    @pytest.mark.asyncio
    async def test_save_without_conn(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test saving metadata using pool connection."""
        metadata = CommandMetadata(
            domain="payments",
            command_id=uuid4(),
            command_type="DebitAccount",
            status=CommandStatus.PENDING,
        )

        await repo.save(metadata, "payments__commands")

        mock_pool._mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_with_external_conn(self, repo: PostgresCommandRepository) -> None:
        """Test saving metadata with external connection."""
        conn = MagicMock()
        conn.execute = AsyncMock()

        metadata = CommandMetadata(
            domain="payments",
            command_id=uuid4(),
            command_type="DebitAccount",
            status=CommandStatus.PENDING,
        )

        await repo.save(metadata, "payments__commands", conn=conn)

        conn.execute.assert_called_once()


class TestPostgresCommandRepositoryGet:
    """Tests for PostgresCommandRepository.get()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()

        now = datetime.now(UTC)
        command_id = uuid4()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(
            return_value=(
                "payments",  # domain
                command_id,  # command_id
                "DebitAccount",  # command_type
                "PENDING",  # status
                0,  # attempts
                3,  # max_attempts
                1,  # msg_id
                None,  # correlation_id
                "",  # reply_queue
                None,  # last_error_type
                None,  # last_error_code
                None,  # last_error_msg
                now,  # created_at
                now,  # updated_at
                None,  # batch_id
            )
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
        pool._command_id = command_id
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> PostgresCommandRepository:
        """Create a repository with mocked pool."""
        return PostgresCommandRepository(mock_pool)

    @pytest.mark.asyncio
    async def test_get_returns_metadata(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test getting existing metadata."""
        result = await repo.get("payments", mock_pool._command_id)

        assert result is not None
        assert result.domain == "payments"
        assert result.command_type == "DebitAccount"
        assert result.status == CommandStatus.PENDING

    @pytest.mark.asyncio
    async def test_get_not_found(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test getting non-existent metadata."""
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=None)

        result = await repo.get("payments", uuid4())

        assert result is None


class TestPostgresCommandRepositoryUpdateStatus:
    """Tests for PostgresCommandRepository.update_status()."""

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
    def repo(self, mock_pool: MagicMock) -> PostgresCommandRepository:
        """Create a repository with mocked pool."""
        return PostgresCommandRepository(mock_pool)

    @pytest.mark.asyncio
    async def test_update_status(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test updating command status."""
        command_id = uuid4()
        await repo.update_status("payments", command_id, CommandStatus.COMPLETED)

        mock_pool._mock_conn.execute.assert_called_once()


class TestPostgresCommandRepositoryUpdateMsgId:
    """Tests for PostgresCommandRepository.update_msg_id()."""

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
    def repo(self, mock_pool: MagicMock) -> PostgresCommandRepository:
        """Create a repository with mocked pool."""
        return PostgresCommandRepository(mock_pool)

    @pytest.mark.asyncio
    async def test_update_msg_id(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test updating message ID."""
        command_id = uuid4()
        await repo.update_msg_id("payments", command_id, 123)

        mock_pool._mock_conn.execute.assert_called_once()


class TestPostgresCommandRepositoryExists:
    """Tests for PostgresCommandRepository.exists()."""

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
    def repo(self, mock_pool: MagicMock) -> PostgresCommandRepository:
        """Create a repository with mocked pool."""
        return PostgresCommandRepository(mock_pool)

    @pytest.mark.asyncio
    async def test_exists_returns_true(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test exists returns true when command exists."""
        result = await repo.exists("payments", uuid4())

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_returns_false(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test exists returns false when command doesn't exist."""
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=(False,))

        result = await repo.exists("payments", uuid4())

        assert result is False

    @pytest.mark.asyncio
    async def test_exists_no_row(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test exists returns false when no row returned."""
        mock_pool._mock_cursor.fetchone = AsyncMock(return_value=None)

        result = await repo.exists("payments", uuid4())

        assert result is False


class TestPostgresAuditLoggerLog:
    """Tests for PostgresAuditLogger.log()."""

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
    def logger(self, mock_pool: MagicMock) -> PostgresAuditLogger:
        """Create an audit logger with mocked pool."""
        return PostgresAuditLogger(mock_pool)

    @pytest.mark.asyncio
    async def test_log_without_details(
        self, logger: PostgresAuditLogger, mock_pool: MagicMock
    ) -> None:
        """Test logging without details."""
        command_id = uuid4()
        await logger.log("payments", command_id, AuditEventType.SENT)

        mock_pool._mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_with_details(
        self, logger: PostgresAuditLogger, mock_pool: MagicMock
    ) -> None:
        """Test logging with details."""
        command_id = uuid4()
        await logger.log(
            "payments",
            command_id,
            AuditEventType.SENT,
            details={"command_type": "DebitAccount"},
        )

        mock_pool._mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_with_external_conn(self, logger: PostgresAuditLogger) -> None:
        """Test logging with external connection."""
        conn = MagicMock()
        conn.execute = AsyncMock()

        command_id = uuid4()
        await logger.log("payments", command_id, AuditEventType.SENT, conn=conn)

        conn.execute.assert_called_once()


class TestPostgresAuditLoggerGetEvents:
    """Tests for PostgresAuditLogger.get_events()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()

        command_id = uuid4()
        now = datetime.now(UTC)
        cursor.execute = AsyncMock()
        cursor.fetchall = AsyncMock(
            return_value=[
                (1, "payments", command_id, "SENT", now, {"key": "value"}),
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
        pool._command_id = command_id
        return pool

    @pytest.fixture
    def logger(self, mock_pool: MagicMock) -> PostgresAuditLogger:
        """Create an audit logger with mocked pool."""
        return PostgresAuditLogger(mock_pool)

    @pytest.mark.asyncio
    async def test_get_events(self, logger: PostgresAuditLogger, mock_pool: MagicMock) -> None:
        """Test getting audit events."""
        events = await logger.get_events(mock_pool._command_id)

        assert len(events) == 1
        assert isinstance(events[0], AuditEvent)
        assert events[0].event_type == "SENT"
        assert events[0].details == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_events_with_domain(
        self, logger: PostgresAuditLogger, mock_pool: MagicMock
    ) -> None:
        """Test getting audit events with domain filter."""
        events = await logger.get_events(mock_pool._command_id, domain="payments")

        assert len(events) == 1
        assert isinstance(events[0], AuditEvent)

    @pytest.mark.asyncio
    async def test_get_events_empty(
        self, logger: PostgresAuditLogger, mock_pool: MagicMock
    ) -> None:
        """Test getting events when none exist."""
        mock_pool._mock_cursor.fetchall = AsyncMock(return_value=[])

        events = await logger.get_events(uuid4())

        assert events == []

    @pytest.mark.asyncio
    async def test_get_events_null_details(
        self, logger: PostgresAuditLogger, mock_pool: MagicMock
    ) -> None:
        """Test getting events with null details."""
        command_id = uuid4()
        now = datetime.now(UTC)
        mock_pool._mock_cursor.fetchall = AsyncMock(
            return_value=[
                (1, "payments", command_id, "SENT", now, None),
            ]
        )

        events = await logger.get_events(command_id)

        assert events[0].details is None

    @pytest.mark.asyncio
    async def test_get_events_returns_audit_event_objects(
        self, logger: PostgresAuditLogger, mock_pool: MagicMock
    ) -> None:
        """Test that get_events returns AuditEvent objects with correct attributes."""
        command_id = uuid4()
        now = datetime.now(UTC)
        mock_pool._mock_cursor.fetchall = AsyncMock(
            return_value=[
                (1, "payments", command_id, "SENT", now, {"msg_id": 42}),
                (2, "payments", command_id, "RECEIVED", now, None),
            ]
        )

        events = await logger.get_events(command_id)

        assert len(events) == 2

        # Check first event
        assert events[0].audit_id == 1
        assert events[0].domain == "payments"
        assert events[0].command_id == command_id
        assert events[0].event_type == "SENT"
        assert events[0].timestamp == now
        assert events[0].details == {"msg_id": 42}

        # Check second event
        assert events[1].audit_id == 2
        assert events[1].event_type == "RECEIVED"
        assert events[1].details is None


class TestPostgresCommandRepositoryQuery:
    """Tests for PostgresCommandRepository.query()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()

        now = datetime.now(UTC)
        command_id = uuid4()
        correlation_id = uuid4()

        cursor.execute = AsyncMock()
        cursor.fetchall = AsyncMock(
            return_value=[
                (
                    "payments",  # domain
                    command_id,  # command_id
                    "DebitAccount",  # command_type
                    "PENDING",  # status
                    0,  # attempts
                    3,  # max_attempts
                    1,  # msg_id
                    correlation_id,  # correlation_id
                    "",  # reply_queue
                    None,  # last_error_type
                    None,  # last_error_code
                    None,  # last_error_msg
                    now,  # created_at
                    now,  # updated_at
                    None,  # batch_id
                ),
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
        pool._command_id = command_id
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock) -> PostgresCommandRepository:
        """Create a repository with mocked pool."""
        return PostgresCommandRepository(mock_pool)

    @pytest.mark.asyncio
    async def test_query_returns_command_metadata(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test query returns list of CommandMetadata."""
        result = await repo.query()

        assert len(result) == 1
        assert result[0].domain == "payments"
        assert result[0].command_type == "DebitAccount"
        assert result[0].status == CommandStatus.PENDING

    @pytest.mark.asyncio
    async def test_query_with_status_filter(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test query with status filter."""
        await repo.query(status=CommandStatus.PENDING)

        mock_pool._mock_cursor.execute.assert_called_once()
        call_args = mock_pool._mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "status = %s" in sql
        assert "PENDING" in params

    @pytest.mark.asyncio
    async def test_query_with_domain_filter(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test query with domain filter."""
        await repo.query(domain="payments")

        mock_pool._mock_cursor.execute.assert_called_once()
        call_args = mock_pool._mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "domain = %s" in sql
        assert "payments" in params

    @pytest.mark.asyncio
    async def test_query_with_command_type_filter(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test query with command_type filter."""
        await repo.query(command_type="DebitAccount")

        mock_pool._mock_cursor.execute.assert_called_once()
        call_args = mock_pool._mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "command_type = %s" in sql
        assert "DebitAccount" in params

    @pytest.mark.asyncio
    async def test_query_with_date_filters(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test query with date range filters."""
        now = datetime.now(UTC)
        created_after = now
        created_before = now

        await repo.query(created_after=created_after, created_before=created_before)

        mock_pool._mock_cursor.execute.assert_called_once()
        call_args = mock_pool._mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "created_at >= %s" in sql
        assert "created_at <= %s" in sql
        assert created_after in params
        assert created_before in params

    @pytest.mark.asyncio
    async def test_query_with_pagination(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test query with pagination."""
        await repo.query(limit=50, offset=100)

        mock_pool._mock_cursor.execute.assert_called_once()
        call_args = mock_pool._mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "LIMIT %s OFFSET %s" in sql
        assert 50 in params
        assert 100 in params

    @pytest.mark.asyncio
    async def test_query_orders_by_created_at_desc(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test query orders by created_at descending."""
        await repo.query()

        mock_pool._mock_cursor.execute.assert_called_once()
        call_args = mock_pool._mock_cursor.execute.call_args
        sql = call_args[0][0]

        assert "ORDER BY created_at DESC" in sql

    @pytest.mark.asyncio
    async def test_query_combined_filters(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test query with multiple combined filters."""
        await repo.query(
            status=CommandStatus.PENDING,
            domain="payments",
            command_type="DebitAccount",
        )

        mock_pool._mock_cursor.execute.assert_called_once()
        call_args = mock_pool._mock_cursor.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]

        assert "status = %s" in sql
        assert "domain = %s" in sql
        assert "command_type = %s" in sql
        assert " AND " in sql
        assert "PENDING" in params
        assert "payments" in params
        assert "DebitAccount" in params

    @pytest.mark.asyncio
    async def test_query_empty_result(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test query returns empty list when no matches."""
        mock_pool._mock_cursor.fetchall = AsyncMock(return_value=[])

        result = await repo.query()

        assert result == []

    @pytest.mark.asyncio
    async def test_query_no_filters_uses_true(
        self, repo: PostgresCommandRepository, mock_pool: MagicMock
    ) -> None:
        """Test query with no filters uses TRUE in WHERE clause."""
        await repo.query()

        mock_pool._mock_cursor.execute.assert_called_once()
        call_args = mock_pool._mock_cursor.execute.call_args
        sql = call_args[0][0]

        assert "WHERE TRUE" in sql
