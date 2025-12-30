"""Unit tests for handler registry."""

from uuid import uuid4

import pytest

from commandbus.exceptions import HandlerAlreadyRegisteredError, HandlerNotFoundError
from commandbus.handler import HandlerRegistry
from commandbus.models import Command, HandlerContext


@pytest.fixture
def registry() -> HandlerRegistry:
    """Create a fresh handler registry for each test."""
    return HandlerRegistry()


@pytest.fixture
def sample_command() -> Command:
    """Create a sample command for testing."""
    return Command(
        domain="payments",
        command_type="DebitAccount",
        command_id=uuid4(),
        data={"account_id": "123", "amount": 100},
    )


@pytest.fixture
def sample_context(sample_command: Command) -> HandlerContext:
    """Create a sample handler context."""
    return HandlerContext(
        command=sample_command,
        attempt=1,
        max_attempts=3,
        msg_id=1,
    )


class TestHandlerRegistration:
    """Tests for handler registration."""

    def test_register_handler(self, registry: HandlerRegistry) -> None:
        """Test that a handler can be registered."""

        async def handler(cmd: Command, ctx: HandlerContext) -> dict:
            return {"handled": True}

        registry.register("payments", "DebitAccount", handler)

        assert registry.has_handler("payments", "DebitAccount")

    def test_register_handler_stores_in_registry(self, registry: HandlerRegistry) -> None:
        """Test that registered handler is stored correctly."""

        async def handler(cmd: Command, ctx: HandlerContext) -> dict:
            return {"handled": True}

        registry.register("payments", "DebitAccount", handler)

        retrieved = registry.get("payments", "DebitAccount")
        assert retrieved is handler

    def test_duplicate_handler_raises_error(self, registry: HandlerRegistry) -> None:
        """Test that registering a duplicate handler raises error."""

        async def handler1(cmd: Command, ctx: HandlerContext) -> None:
            pass

        async def handler2(cmd: Command, ctx: HandlerContext) -> None:
            pass

        registry.register("payments", "DebitAccount", handler1)

        with pytest.raises(HandlerAlreadyRegisteredError) as exc_info:
            registry.register("payments", "DebitAccount", handler2)

        assert exc_info.value.domain == "payments"
        assert exc_info.value.command_type == "DebitAccount"
        assert "payments.DebitAccount" in str(exc_info.value)

    def test_original_handler_preserved_after_duplicate_attempt(
        self, registry: HandlerRegistry
    ) -> None:
        """Test that original handler is preserved when duplicate registration fails."""

        async def handler1(cmd: Command, ctx: HandlerContext) -> str:
            return "handler1"

        async def handler2(cmd: Command, ctx: HandlerContext) -> str:
            return "handler2"

        registry.register("payments", "DebitAccount", handler1)

        with pytest.raises(HandlerAlreadyRegisteredError):
            registry.register("payments", "DebitAccount", handler2)

        # Original handler should still be there
        assert registry.get("payments", "DebitAccount") is handler1

    def test_same_command_type_different_domains(self, registry: HandlerRegistry) -> None:
        """Test that same command type can be registered for different domains."""

        async def payments_handler(cmd: Command, ctx: HandlerContext) -> None:
            pass

        async def reports_handler(cmd: Command, ctx: HandlerContext) -> None:
            pass

        registry.register("payments", "Process", payments_handler)
        registry.register("reports", "Process", reports_handler)

        assert registry.get("payments", "Process") is payments_handler
        assert registry.get("reports", "Process") is reports_handler


class TestHandlerDecorator:
    """Tests for the handler decorator."""

    def test_decorator_registers_handler(self, registry: HandlerRegistry) -> None:
        """Test that decorator registers the handler."""

        @registry.handler("payments", "DebitAccount")
        async def handle_debit(cmd: Command, ctx: HandlerContext) -> None:
            pass

        assert registry.has_handler("payments", "DebitAccount")

    def test_decorator_returns_function_unchanged(self, registry: HandlerRegistry) -> None:
        """Test that decorated function is returned unchanged."""

        async def original_handler(cmd: Command, ctx: HandlerContext) -> str:
            return "result"

        decorated = registry.handler("payments", "DebitAccount")(original_handler)

        assert decorated is original_handler

    def test_decorator_duplicate_raises_error(self, registry: HandlerRegistry) -> None:
        """Test that decorator raises error on duplicate registration."""

        @registry.handler("payments", "DebitAccount")
        async def handler1(cmd: Command, ctx: HandlerContext) -> None:
            pass

        with pytest.raises(HandlerAlreadyRegisteredError):

            @registry.handler("payments", "DebitAccount")
            async def handler2(cmd: Command, ctx: HandlerContext) -> None:
                pass


class TestHandlerLookup:
    """Tests for handler lookup."""

    def test_get_returns_none_for_missing(self, registry: HandlerRegistry) -> None:
        """Test that get returns None for unregistered handler."""
        result = registry.get("payments", "Unknown")
        assert result is None

    def test_get_or_raise_for_missing(self, registry: HandlerRegistry) -> None:
        """Test that get_or_raise raises for unregistered handler."""
        with pytest.raises(HandlerNotFoundError) as exc_info:
            registry.get_or_raise("payments", "Unknown")

        assert exc_info.value.domain == "payments"
        assert exc_info.value.command_type == "Unknown"

    def test_has_handler_returns_false_for_missing(self, registry: HandlerRegistry) -> None:
        """Test that has_handler returns False for unregistered handler."""
        assert not registry.has_handler("payments", "Unknown")

    def test_has_handler_returns_true_for_registered(self, registry: HandlerRegistry) -> None:
        """Test that has_handler returns True for registered handler."""

        async def handler(cmd: Command, ctx: HandlerContext) -> None:
            pass

        registry.register("payments", "DebitAccount", handler)

        assert registry.has_handler("payments", "DebitAccount")


class TestHandlerDispatch:
    """Tests for command dispatch."""

    @pytest.mark.asyncio
    async def test_dispatch_to_handler(
        self,
        registry: HandlerRegistry,
        sample_command: Command,
        sample_context: HandlerContext,
    ) -> None:
        """Test that dispatch calls the registered handler."""
        handler_called = False
        received_command = None
        received_context = None

        async def handler(cmd: Command, ctx: HandlerContext) -> dict:
            nonlocal handler_called, received_command, received_context
            handler_called = True
            received_command = cmd
            received_context = ctx
            return {"success": True}

        registry.register("payments", "DebitAccount", handler)

        result = await registry.dispatch(sample_command, sample_context)

        assert handler_called
        assert received_command is sample_command
        assert received_context is sample_context
        assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_dispatch_receives_command_data(
        self,
        registry: HandlerRegistry,
        sample_context: HandlerContext,
    ) -> None:
        """Test that handler receives the command data."""
        command = Command(
            domain="payments",
            command_type="DebitAccount",
            command_id=uuid4(),
            data={"account_id": "456", "amount": 250},
        )
        context = HandlerContext(
            command=command,
            attempt=1,
            max_attempts=3,
            msg_id=1,
        )

        received_data = None

        async def handler(cmd: Command, ctx: HandlerContext) -> None:
            nonlocal received_data
            received_data = cmd.data

        registry.register("payments", "DebitAccount", handler)

        await registry.dispatch(command, context)

        assert received_data == {"account_id": "456", "amount": 250}

    @pytest.mark.asyncio
    async def test_dispatch_raises_for_missing_handler(
        self,
        registry: HandlerRegistry,
        sample_command: Command,
        sample_context: HandlerContext,
    ) -> None:
        """Test that dispatch raises when no handler is registered."""
        # Don't register any handler

        with pytest.raises(HandlerNotFoundError):
            await registry.dispatch(sample_command, sample_context)


class TestRegistryManagement:
    """Tests for registry management functions."""

    def test_registered_handlers_empty(self, registry: HandlerRegistry) -> None:
        """Test that registered_handlers returns empty list initially."""
        assert registry.registered_handlers() == []

    def test_registered_handlers_lists_all(self, registry: HandlerRegistry) -> None:
        """Test that registered_handlers lists all registered handlers."""

        async def handler1(cmd: Command, ctx: HandlerContext) -> None:
            pass

        async def handler2(cmd: Command, ctx: HandlerContext) -> None:
            pass

        registry.register("payments", "Debit", handler1)
        registry.register("payments", "Credit", handler2)
        registry.register("reports", "Generate", handler1)

        handlers = registry.registered_handlers()

        assert len(handlers) == 3
        assert ("payments", "Debit") in handlers
        assert ("payments", "Credit") in handlers
        assert ("reports", "Generate") in handlers

    def test_clear_removes_all_handlers(self, registry: HandlerRegistry) -> None:
        """Test that clear removes all registered handlers."""

        async def handler(cmd: Command, ctx: HandlerContext) -> None:
            pass

        registry.register("payments", "Debit", handler)
        registry.register("payments", "Credit", handler)

        registry.clear()

        assert registry.registered_handlers() == []
        assert not registry.has_handler("payments", "Debit")
        assert not registry.has_handler("payments", "Credit")


class TestNoHandlerLogsWarning:
    """Tests for missing handler behavior."""

    @pytest.mark.asyncio
    async def test_no_handler_raises_not_found(
        self,
        registry: HandlerRegistry,
    ) -> None:
        """Test that missing handler raises HandlerNotFoundError."""
        command = Command(
            domain="payments",
            command_type="RefundPayment",
            command_id=uuid4(),
            data={},
        )
        context = HandlerContext(
            command=command,
            attempt=1,
            max_attempts=3,
            msg_id=1,
        )

        with pytest.raises(HandlerNotFoundError) as exc_info:
            await registry.dispatch(command, context)

        assert "RefundPayment" in str(exc_info.value)
