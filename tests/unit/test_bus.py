"""Unit tests for CommandBus send functionality."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from commandbus.bus import CommandBus, _chunked, _make_queue_name
from commandbus.exceptions import DuplicateCommandError
from commandbus.models import AuditEvent, BatchSendResult, CommandStatus, SendRequest, SendResult
from commandbus.repositories.audit import AuditEventType


class TestMakeQueueName:
    """Tests for queue name generation."""

    def test_default_suffix(self) -> None:
        """Test queue name with default suffix."""
        result = _make_queue_name("payments")
        assert result == "payments__commands"

    def test_custom_suffix(self) -> None:
        """Test queue name with custom suffix."""
        result = _make_queue_name("payments", "replies")
        assert result == "payments__replies"


class TestSendResult:
    """Tests for SendResult dataclass."""

    def test_send_result_creation(self) -> None:
        """Test creating a SendResult."""
        cmd_id = uuid4()
        result = SendResult(command_id=cmd_id, msg_id=123)

        assert result.command_id == cmd_id
        assert result.msg_id == 123


class TestCommandBusSend:
    """Tests for CommandBus.send() method."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool with proper async context managers."""
        pool = MagicMock()
        conn = MagicMock()

        # Create async context managers
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
    async def test_send_valid_command(self, command_bus: CommandBus) -> None:
        """Test sending a valid command."""
        command_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock) as mock_save,
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock) as mock_audit,
        ):
            mock_exists.return_value = False
            mock_pgmq_send.return_value = 42

            result = await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"account_id": "123", "amount": 100},
            )

            assert result.command_id == command_id
            assert result.msg_id == 42

            mock_exists.assert_called_once()
            mock_pgmq_send.assert_called_once()
            mock_save.assert_called_once()
            mock_audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_with_correlation_id(self, command_bus: CommandBus) -> None:
        """Test sending command with correlation ID."""
        command_id = uuid4()
        correlation_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock) as mock_save,
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_exists.return_value = False
            mock_pgmq_send.return_value = 42

            result = await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"account_id": "123"},
                correlation_id=correlation_id,
            )

            assert result.command_id == command_id

            # Check that correlation_id was passed to save
            save_call = mock_save.call_args
            metadata = save_call[0][0]
            assert metadata.correlation_id == correlation_id

    @pytest.mark.asyncio
    async def test_send_with_reply_to(self, command_bus: CommandBus) -> None:
        """Test sending command with reply queue."""
        command_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock) as mock_save,
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_exists.return_value = False
            mock_pgmq_send.return_value = 42

            result = await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"account_id": "123"},
                reply_to="payments__replies",
            )

            assert result.command_id == command_id

            # Check that reply_to was passed to save
            save_call = mock_save.call_args
            metadata = save_call[0][0]
            assert metadata.reply_to == "payments__replies"

    @pytest.mark.asyncio
    async def test_send_generates_correlation_id_when_not_provided(
        self, command_bus: CommandBus
    ) -> None:
        """Test that correlation_id is auto-generated when not provided."""
        command_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock) as mock_save,
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock) as mock_audit,
        ):
            mock_exists.return_value = False
            mock_pgmq_send.return_value = 42

            await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"account_id": "123"},
                # No correlation_id provided
            )

            # Check that correlation_id was auto-generated in metadata
            save_call = mock_save.call_args
            metadata = save_call[0][0]
            assert metadata.correlation_id is not None

            # Check that correlation_id is in the message payload
            pgmq_call = mock_pgmq_send.call_args
            message = pgmq_call[0][1]
            assert "correlation_id" in message
            assert message["correlation_id"] == str(metadata.correlation_id)

            # Check that correlation_id is in audit details
            audit_call = mock_audit.call_args
            assert audit_call[1]["details"]["correlation_id"] == str(metadata.correlation_id)

    @pytest.mark.asyncio
    async def test_send_correlation_id_in_message_payload(self, command_bus: CommandBus) -> None:
        """Test that explicit correlation_id is included in message payload."""
        command_id = uuid4()
        correlation_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_exists.return_value = False
            mock_pgmq_send.return_value = 42

            await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"account_id": "123"},
                correlation_id=correlation_id,
            )

            # Check that correlation_id is in the message payload
            pgmq_call = mock_pgmq_send.call_args
            message = pgmq_call[0][1]
            assert message["correlation_id"] == str(correlation_id)

    @pytest.mark.asyncio
    async def test_send_duplicate_command_raises_error(self, command_bus: CommandBus) -> None:
        """Test that duplicate command raises DuplicateCommandError."""
        command_id = uuid4()

        with patch.object(
            command_bus._command_repo, "exists", new_callable=AsyncMock
        ) as mock_exists:
            mock_exists.return_value = True

            with pytest.raises(DuplicateCommandError) as exc_info:
                await command_bus.send(
                    domain="payments",
                    command_type="DebitAccount",
                    command_id=command_id,
                    data={"account_id": "123"},
                )

            assert exc_info.value.domain == "payments"
            assert str(command_id) in exc_info.value.command_id

    @pytest.mark.asyncio
    async def test_send_same_id_different_domain_allowed(self, command_bus: CommandBus) -> None:
        """Test that same command_id is allowed in different domains."""
        command_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock),
        ):
            # exists() checks per-domain, so same ID in different domain returns False
            mock_exists.return_value = False
            mock_pgmq_send.return_value = 42

            # Send to first domain
            result1 = await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"account_id": "123"},
            )

            # Send same command_id to different domain - should succeed
            result2 = await command_bus.send(
                domain="reports",
                command_type="GenerateReport",
                command_id=command_id,
                data={"report_type": "summary"},
            )

            assert result1.command_id == command_id
            assert result2.command_id == command_id
            # Both should have different msg_ids from PGMQ
            assert mock_pgmq_send.call_count == 2

    @pytest.mark.asyncio
    async def test_send_stores_pending_status(self, command_bus: CommandBus) -> None:
        """Test that command is stored with PENDING status."""
        command_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock) as mock_save,
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_exists.return_value = False
            mock_pgmq_send.return_value = 42

            await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"account_id": "123"},
            )

            save_call = mock_save.call_args
            metadata = save_call[0][0]
            assert metadata.status == CommandStatus.PENDING

    @pytest.mark.asyncio
    async def test_send_records_audit_event(self, command_bus: CommandBus) -> None:
        """Test that SENT audit event is recorded."""
        command_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock) as mock_audit,
        ):
            mock_exists.return_value = False
            mock_pgmq_send.return_value = 42

            await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"account_id": "123"},
            )

            mock_audit.assert_called_once()
            call_kwargs = mock_audit.call_args[1]
            assert call_kwargs["domain"] == "payments"
            assert call_kwargs["command_id"] == command_id
            assert call_kwargs["event_type"] == AuditEventType.SENT
            assert "command_type" in call_kwargs["details"]

    @pytest.mark.asyncio
    async def test_send_uses_default_max_attempts(self, command_bus: CommandBus) -> None:
        """Test that default max_attempts is used when not specified."""
        command_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock) as mock_save,
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_exists.return_value = False
            mock_pgmq_send.return_value = 42

            await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"account_id": "123"},
            )

            save_call = mock_save.call_args
            metadata = save_call[0][0]
            assert metadata.max_attempts == 3  # default

    @pytest.mark.asyncio
    async def test_send_uses_custom_max_attempts(self, command_bus: CommandBus) -> None:
        """Test that custom max_attempts is used when specified."""
        command_id = uuid4()

        with (
            patch.object(
                command_bus._command_repo, "exists", new_callable=AsyncMock
            ) as mock_exists,
            patch.object(command_bus._pgmq, "send", new_callable=AsyncMock) as mock_pgmq_send,
            patch.object(command_bus._command_repo, "save", new_callable=AsyncMock) as mock_save,
            patch.object(command_bus._audit_logger, "log", new_callable=AsyncMock),
        ):
            mock_exists.return_value = False
            mock_pgmq_send.return_value = 42

            await command_bus.send(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"account_id": "123"},
                max_attempts=5,
            )

            save_call = mock_save.call_args
            metadata = save_call[0][0]
            assert metadata.max_attempts == 5


class TestCommandBusBuildMessage:
    """Tests for message building."""

    @pytest.fixture
    def command_bus(self) -> CommandBus:
        """Create a CommandBus with mocked pool."""
        pool = MagicMock()
        return CommandBus(pool)

    def test_build_message_basic(self, command_bus: CommandBus) -> None:
        """Test building a basic message."""
        command_id = uuid4()
        correlation_id = uuid4()
        message = command_bus._build_message(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
            correlation_id=correlation_id,
            reply_to=None,
        )

        assert message["domain"] == "payments"
        assert message["command_type"] == "DebitAccount"
        assert message["command_id"] == str(command_id)
        assert message["data"] == {"account_id": "123"}
        assert message["correlation_id"] == str(correlation_id)
        assert "reply_to" not in message

    def test_build_message_with_correlation_id(self, command_bus: CommandBus) -> None:
        """Test building message with correlation ID."""
        command_id = uuid4()
        correlation_id = uuid4()
        message = command_bus._build_message(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
            correlation_id=correlation_id,
            reply_to=None,
        )

        assert message["correlation_id"] == str(correlation_id)

    def test_build_message_with_reply_to(self, command_bus: CommandBus) -> None:
        """Test building message with reply_to."""
        command_id = uuid4()
        correlation_id = uuid4()
        message = command_bus._build_message(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"account_id": "123"},
            correlation_id=correlation_id,
            reply_to="payments__replies",
        )

        assert message["reply_to"] == "payments__replies"
        assert message["correlation_id"] == str(correlation_id)


class TestCommandBusGetCommand:
    """Tests for CommandBus.get_command()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        return MagicMock()

    @pytest.fixture
    def command_bus(self, mock_pool: MagicMock) -> CommandBus:
        """Create a CommandBus with mocked dependencies."""
        return CommandBus(mock_pool)

    @pytest.mark.asyncio
    async def test_get_command_delegates_to_repo(self, command_bus: CommandBus) -> None:
        """Test that get_command delegates to repository."""
        command_id = uuid4()

        with patch.object(command_bus._command_repo, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            result = await command_bus.get_command("payments", command_id)

            assert result is None
            mock_get.assert_called_once_with("payments", command_id)


class TestCommandBusCommandExists:
    """Tests for CommandBus.command_exists()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        return MagicMock()

    @pytest.fixture
    def command_bus(self, mock_pool: MagicMock) -> CommandBus:
        """Create a CommandBus with mocked dependencies."""
        return CommandBus(mock_pool)

    @pytest.mark.asyncio
    async def test_command_exists_delegates_to_repo(self, command_bus: CommandBus) -> None:
        """Test that command_exists delegates to repository."""
        command_id = uuid4()

        with patch.object(
            command_bus._command_repo, "exists", new_callable=AsyncMock
        ) as mock_exists:
            mock_exists.return_value = True

            result = await command_bus.command_exists("payments", command_id)

            assert result is True
            mock_exists.assert_called_once_with("payments", command_id)


class TestCommandBusGetAuditTrail:
    """Tests for CommandBus.get_audit_trail()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        return MagicMock()

    @pytest.fixture
    def command_bus(self, mock_pool: MagicMock) -> CommandBus:
        """Create a CommandBus with mocked dependencies."""
        return CommandBus(mock_pool)

    @pytest.mark.asyncio
    async def test_get_audit_trail_delegates_to_logger(self, command_bus: CommandBus) -> None:
        """Test that get_audit_trail delegates to audit logger."""
        command_id = uuid4()

        mock_events = [
            AuditEvent(
                audit_id=1,
                domain="payments",
                command_id=command_id,
                event_type="SENT",
                timestamp=datetime.now(UTC),
                details={"msg_id": 42},
            ),
        ]

        with patch.object(
            command_bus._audit_logger, "get_events", new_callable=AsyncMock
        ) as mock_get_events:
            mock_get_events.return_value = mock_events

            result = await command_bus.get_audit_trail(command_id)

            assert result == mock_events
            mock_get_events.assert_called_once_with(command_id, None)

    @pytest.mark.asyncio
    async def test_get_audit_trail_with_domain(self, command_bus: CommandBus) -> None:
        """Test get_audit_trail with domain filter."""
        command_id = uuid4()

        with patch.object(
            command_bus._audit_logger, "get_events", new_callable=AsyncMock
        ) as mock_get_events:
            mock_get_events.return_value = []

            await command_bus.get_audit_trail(command_id, domain="payments")

            mock_get_events.assert_called_once_with(command_id, "payments")

    @pytest.mark.asyncio
    async def test_get_audit_trail_returns_empty_for_unknown(self, command_bus: CommandBus) -> None:
        """Test get_audit_trail returns empty list for unknown command."""
        command_id = uuid4()

        with patch.object(
            command_bus._audit_logger, "get_events", new_callable=AsyncMock
        ) as mock_get_events:
            mock_get_events.return_value = []

            result = await command_bus.get_audit_trail(command_id)

            assert result == []

    @pytest.mark.asyncio
    async def test_get_audit_trail_returns_chronological_order(
        self, command_bus: CommandBus
    ) -> None:
        """Test get_audit_trail returns events in chronological order."""
        command_id = uuid4()

        now = datetime.now(UTC)
        mock_events = [
            AuditEvent(
                audit_id=1,
                domain="payments",
                command_id=command_id,
                event_type="SENT",
                timestamp=now,
                details=None,
            ),
            AuditEvent(
                audit_id=2,
                domain="payments",
                command_id=command_id,
                event_type="RECEIVED",
                timestamp=now + timedelta(seconds=1),
                details=None,
            ),
            AuditEvent(
                audit_id=3,
                domain="payments",
                command_id=command_id,
                event_type="COMPLETED",
                timestamp=now + timedelta(seconds=2),
                details=None,
            ),
        ]

        with patch.object(
            command_bus._audit_logger, "get_events", new_callable=AsyncMock
        ) as mock_get_events:
            mock_get_events.return_value = mock_events

            result = await command_bus.get_audit_trail(command_id)

            assert len(result) == 3
            assert result[0].event_type == "SENT"
            assert result[1].event_type == "RECEIVED"
            assert result[2].event_type == "COMPLETED"


class TestCommandBusQueryCommands:
    """Tests for CommandBus.query_commands()."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock connection pool."""
        return MagicMock()

    @pytest.fixture
    def command_bus(self, mock_pool: MagicMock) -> CommandBus:
        """Create a CommandBus with mocked dependencies."""
        return CommandBus(mock_pool)

    @pytest.mark.asyncio
    async def test_query_commands_delegates_to_repo(self, command_bus: CommandBus) -> None:
        """Test that query_commands delegates to repository."""
        with patch.object(command_bus._command_repo, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []

            result = await command_bus.query_commands()

            assert result == []
            mock_query.assert_called_once_with(
                status=None,
                domain=None,
                command_type=None,
                created_after=None,
                created_before=None,
                limit=100,
                offset=0,
            )

    @pytest.mark.asyncio
    async def test_query_commands_with_status_filter(self, command_bus: CommandBus) -> None:
        """Test query_commands with status filter."""
        with patch.object(command_bus._command_repo, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []

            await command_bus.query_commands(status=CommandStatus.PENDING)

            mock_query.assert_called_once()
            call_kwargs = mock_query.call_args[1]
            assert call_kwargs["status"] == CommandStatus.PENDING

    @pytest.mark.asyncio
    async def test_query_commands_with_domain_filter(self, command_bus: CommandBus) -> None:
        """Test query_commands with domain filter."""
        with patch.object(command_bus._command_repo, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []

            await command_bus.query_commands(domain="payments")

            mock_query.assert_called_once()
            call_kwargs = mock_query.call_args[1]
            assert call_kwargs["domain"] == "payments"

    @pytest.mark.asyncio
    async def test_query_commands_with_command_type_filter(self, command_bus: CommandBus) -> None:
        """Test query_commands with command_type filter."""
        with patch.object(command_bus._command_repo, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []

            await command_bus.query_commands(command_type="DebitAccount")

            mock_query.assert_called_once()
            call_kwargs = mock_query.call_args[1]
            assert call_kwargs["command_type"] == "DebitAccount"

    @pytest.mark.asyncio
    async def test_query_commands_with_date_filters(self, command_bus: CommandBus) -> None:
        """Test query_commands with date range filters."""
        now = datetime.now(UTC)
        created_after = now - timedelta(days=7)
        created_before = now

        with patch.object(command_bus._command_repo, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []

            await command_bus.query_commands(
                created_after=created_after,
                created_before=created_before,
            )

            mock_query.assert_called_once()
            call_kwargs = mock_query.call_args[1]
            assert call_kwargs["created_after"] == created_after
            assert call_kwargs["created_before"] == created_before

    @pytest.mark.asyncio
    async def test_query_commands_with_pagination(self, command_bus: CommandBus) -> None:
        """Test query_commands with pagination."""
        with patch.object(command_bus._command_repo, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []

            await command_bus.query_commands(limit=50, offset=100)

            mock_query.assert_called_once()
            call_kwargs = mock_query.call_args[1]
            assert call_kwargs["limit"] == 50
            assert call_kwargs["offset"] == 100

    @pytest.mark.asyncio
    async def test_query_commands_with_combined_filters(self, command_bus: CommandBus) -> None:
        """Test query_commands with multiple filters combined."""
        with patch.object(command_bus._command_repo, "query", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = []

            await command_bus.query_commands(
                status=CommandStatus.PENDING,
                domain="payments",
                command_type="DebitAccount",
                limit=50,
            )

            mock_query.assert_called_once()
            call_kwargs = mock_query.call_args[1]
            assert call_kwargs["status"] == CommandStatus.PENDING
            assert call_kwargs["domain"] == "payments"
            assert call_kwargs["command_type"] == "DebitAccount"
            assert call_kwargs["limit"] == 50


class TestChunked:
    """Tests for _chunked helper function."""

    def test_chunked_exact_division(self) -> None:
        """Test chunking when items divide evenly."""
        items = [1, 2, 3, 4, 5, 6]
        result = _chunked(items, 2)
        assert result == [[1, 2], [3, 4], [5, 6]]

    def test_chunked_with_remainder(self) -> None:
        """Test chunking when items don't divide evenly."""
        items = [1, 2, 3, 4, 5]
        result = _chunked(items, 2)
        assert result == [[1, 2], [3, 4], [5]]

    def test_chunked_single_chunk(self) -> None:
        """Test chunking when chunk size >= list size."""
        items = [1, 2, 3]
        result = _chunked(items, 10)
        assert result == [[1, 2, 3]]

    def test_chunked_empty_list(self) -> None:
        """Test chunking an empty list."""
        items: list[int] = []
        result = _chunked(items, 5)
        assert result == []

    def test_chunked_size_one(self) -> None:
        """Test chunking with size 1."""
        items = [1, 2, 3]
        result = _chunked(items, 1)
        assert result == [[1], [2], [3]]


class TestSendRequest:
    """Tests for SendRequest dataclass."""

    def test_send_request_creation(self) -> None:
        """Test creating a SendRequest."""
        cmd_id = uuid4()
        req = SendRequest(
            domain="payments",
            command_type="DebitAccount",
            command_id=cmd_id,
            data={"amount": 100},
        )

        assert req.domain == "payments"
        assert req.command_type == "DebitAccount"
        assert req.command_id == cmd_id
        assert req.data == {"amount": 100}
        assert req.correlation_id is None
        assert req.reply_to is None
        assert req.max_attempts is None

    def test_send_request_with_all_fields(self) -> None:
        """Test creating a SendRequest with all optional fields."""
        cmd_id = uuid4()
        corr_id = uuid4()
        req = SendRequest(
            domain="payments",
            command_type="DebitAccount",
            command_id=cmd_id,
            data={"amount": 100},
            correlation_id=corr_id,
            reply_to="payments__replies",
            max_attempts=5,
        )

        assert req.correlation_id == corr_id
        assert req.reply_to == "payments__replies"
        assert req.max_attempts == 5


class TestBatchSendResult:
    """Tests for BatchSendResult dataclass."""

    def test_batch_send_result_creation(self) -> None:
        """Test creating a BatchSendResult."""
        cmd_id1 = uuid4()
        cmd_id2 = uuid4()
        results = [
            SendResult(command_id=cmd_id1, msg_id=1),
            SendResult(command_id=cmd_id2, msg_id=2),
        ]

        batch_result = BatchSendResult(
            results=results,
            chunks_processed=1,
            total_commands=2,
        )

        assert len(batch_result.results) == 2
        assert batch_result.chunks_processed == 1
        assert batch_result.total_commands == 2


class TestCommandBusSendBatch:
    """Tests for CommandBus.send_batch() method."""

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
    async def test_send_batch_empty_list(self, command_bus: CommandBus) -> None:
        """Test send_batch with empty list returns empty result."""
        result = await command_bus.send_batch([])

        assert result.results == []
        assert result.chunks_processed == 0
        assert result.total_commands == 0

    @pytest.mark.asyncio
    async def test_send_batch_single_request(self, command_bus: CommandBus) -> None:
        """Test send_batch with a single request."""
        command_id = uuid4()
        request = SendRequest(
            domain="payments",
            command_type="DebitAccount",
            command_id=command_id,
            data={"amount": 100},
        )

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists_batch,
            patch.object(
                command_bus._pgmq, "send_batch", new_callable=AsyncMock
            ) as mock_pgmq_send_batch,
            patch.object(
                command_bus._command_repo, "save_batch", new_callable=AsyncMock
            ) as mock_save_batch,
            patch.object(
                command_bus._audit_logger, "log_batch", new_callable=AsyncMock
            ) as mock_audit_batch,
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock) as mock_notify,
        ):
            mock_exists_batch.return_value = set()
            mock_pgmq_send_batch.return_value = [42]

            result = await command_bus.send_batch([request])

            assert result.total_commands == 1
            assert result.chunks_processed == 1
            assert result.results[0].command_id == command_id
            assert result.results[0].msg_id == 42

            mock_exists_batch.assert_called_once()
            mock_pgmq_send_batch.assert_called_once()
            mock_save_batch.assert_called_once()
            mock_audit_batch.assert_called_once()
            mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_batch_multiple_requests_same_domain(self, command_bus: CommandBus) -> None:
        """Test send_batch with multiple requests in the same domain."""
        requests = [
            SendRequest(
                domain="payments",
                command_type="DebitAccount",
                command_id=uuid4(),
                data={"amount": i * 100},
            )
            for i in range(3)
        ]

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists_batch,
            patch.object(
                command_bus._pgmq, "send_batch", new_callable=AsyncMock
            ) as mock_pgmq_send_batch,
            patch.object(command_bus._command_repo, "save_batch", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists_batch.return_value = set()
            mock_pgmq_send_batch.return_value = [1, 2, 3]

            result = await command_bus.send_batch(requests)

            assert result.total_commands == 3
            assert result.chunks_processed == 1
            assert len(result.results) == 3

    @pytest.mark.asyncio
    async def test_send_batch_multiple_domains(self, command_bus: CommandBus) -> None:
        """Test send_batch with requests across different domains."""
        requests = [
            SendRequest(
                domain="payments",
                command_type="DebitAccount",
                command_id=uuid4(),
                data={"amount": 100},
            ),
            SendRequest(
                domain="notifications",
                command_type="SendEmail",
                command_id=uuid4(),
                data={"email": "test@example.com"},
            ),
        ]

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists_batch,
            patch.object(
                command_bus._pgmq, "send_batch", new_callable=AsyncMock
            ) as mock_pgmq_send_batch,
            patch.object(command_bus._command_repo, "save_batch", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock) as mock_notify,
        ):
            mock_exists_batch.return_value = set()
            mock_pgmq_send_batch.return_value = [1]

            result = await command_bus.send_batch(requests)

            assert result.total_commands == 2
            # NOTIFY should be called once per domain
            assert mock_notify.call_count == 2

    @pytest.mark.asyncio
    async def test_send_batch_duplicate_raises_error(self, command_bus: CommandBus) -> None:
        """Test send_batch raises DuplicateCommandError for existing command."""
        command_id = uuid4()
        requests = [
            SendRequest(
                domain="payments",
                command_type="DebitAccount",
                command_id=command_id,
                data={"amount": 100},
            ),
        ]

        with patch.object(
            command_bus._command_repo, "exists_batch", new_callable=AsyncMock
        ) as mock_exists_batch:
            mock_exists_batch.return_value = {command_id}

            with pytest.raises(DuplicateCommandError) as exc_info:
                await command_bus.send_batch(requests)

            assert exc_info.value.domain == "payments"
            assert str(command_id) in exc_info.value.command_id

    @pytest.mark.asyncio
    async def test_send_batch_with_custom_chunk_size(self, command_bus: CommandBus) -> None:
        """Test send_batch with custom chunk size processes in multiple chunks."""
        requests = [
            SendRequest(
                domain="payments",
                command_type="DebitAccount",
                command_id=uuid4(),
                data={"amount": i * 100},
            )
            for i in range(5)
        ]

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists_batch,
            patch.object(
                command_bus._pgmq, "send_batch", new_callable=AsyncMock
            ) as mock_pgmq_send_batch,
            patch.object(command_bus._command_repo, "save_batch", new_callable=AsyncMock),
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists_batch.return_value = set()
            # Return different msg_ids for each chunk
            mock_pgmq_send_batch.side_effect = [[1, 2], [3, 4], [5]]

            result = await command_bus.send_batch(requests, chunk_size=2)

            assert result.total_commands == 5
            assert result.chunks_processed == 3
            # exists_batch called once per chunk
            assert mock_exists_batch.call_count == 3

    @pytest.mark.asyncio
    async def test_send_batch_uses_default_max_attempts(self, command_bus: CommandBus) -> None:
        """Test that default max_attempts is used when not specified."""
        request = SendRequest(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists_batch,
            patch.object(
                command_bus._pgmq, "send_batch", new_callable=AsyncMock
            ) as mock_pgmq_send_batch,
            patch.object(
                command_bus._command_repo, "save_batch", new_callable=AsyncMock
            ) as mock_save_batch,
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists_batch.return_value = set()
            mock_pgmq_send_batch.return_value = [42]

            await command_bus.send_batch([request])

            # Check metadata in save_batch call
            save_call = mock_save_batch.call_args
            metadata_list = save_call[0][0]
            assert metadata_list[0].max_attempts == 3  # default

    @pytest.mark.asyncio
    async def test_send_batch_uses_custom_max_attempts(self, command_bus: CommandBus) -> None:
        """Test that custom max_attempts is used when specified."""
        request = SendRequest(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
            max_attempts=7,
        )

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists_batch,
            patch.object(
                command_bus._pgmq, "send_batch", new_callable=AsyncMock
            ) as mock_pgmq_send_batch,
            patch.object(
                command_bus._command_repo, "save_batch", new_callable=AsyncMock
            ) as mock_save_batch,
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists_batch.return_value = set()
            mock_pgmq_send_batch.return_value = [42]

            await command_bus.send_batch([request])

            save_call = mock_save_batch.call_args
            metadata_list = save_call[0][0]
            assert metadata_list[0].max_attempts == 7

    @pytest.mark.asyncio
    async def test_send_batch_generates_correlation_id(self, command_bus: CommandBus) -> None:
        """Test that correlation_id is auto-generated when not provided."""
        request = SendRequest(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists_batch,
            patch.object(
                command_bus._pgmq, "send_batch", new_callable=AsyncMock
            ) as mock_pgmq_send_batch,
            patch.object(
                command_bus._command_repo, "save_batch", new_callable=AsyncMock
            ) as mock_save_batch,
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists_batch.return_value = set()
            mock_pgmq_send_batch.return_value = [42]

            await command_bus.send_batch([request])

            save_call = mock_save_batch.call_args
            metadata_list = save_call[0][0]
            assert metadata_list[0].correlation_id is not None

    @pytest.mark.asyncio
    async def test_send_batch_stores_pending_status(self, command_bus: CommandBus) -> None:
        """Test that commands are stored with PENDING status."""
        request = SendRequest(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"amount": 100},
        )

        with (
            patch.object(
                command_bus._command_repo, "exists_batch", new_callable=AsyncMock
            ) as mock_exists_batch,
            patch.object(
                command_bus._pgmq, "send_batch", new_callable=AsyncMock
            ) as mock_pgmq_send_batch,
            patch.object(
                command_bus._command_repo, "save_batch", new_callable=AsyncMock
            ) as mock_save_batch,
            patch.object(command_bus._audit_logger, "log_batch", new_callable=AsyncMock),
            patch.object(command_bus._pgmq, "notify", new_callable=AsyncMock),
        ):
            mock_exists_batch.return_value = set()
            mock_pgmq_send_batch.return_value = [42]

            await command_bus.send_batch([request])

            save_call = mock_save_batch.call_args
            metadata_list = save_call[0][0]
            assert metadata_list[0].status == CommandStatus.PENDING
