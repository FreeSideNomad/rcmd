"""Unit tests for CommandBus send functionality."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from commandbus.bus import CommandBus, SendResult, _make_queue_name
from commandbus.exceptions import DuplicateCommandError
from commandbus.models import AuditEvent, CommandStatus
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
