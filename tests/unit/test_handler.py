"""Unit tests for handler registry."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from commandbus.exceptions import HandlerAlreadyRegisteredError, HandlerNotFoundError
from commandbus.handler import (
    _HANDLER_ATTR,
    HandlerMeta,
    HandlerRegistry,
    get_handler_meta,
    handler,
)
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


class TestStandaloneHandlerDecorator:
    """Tests for the standalone @handler decorator for class methods."""

    def test_handler_decorator_sets_metadata(self) -> None:
        """Test that @handler decorator attaches metadata to method."""

        class MyHandlers:
            @handler(domain="payments", command_type="DebitAccount")
            async def handle_debit(self, cmd: Command, ctx: HandlerContext) -> dict:
                return {"status": "ok"}

        meta = getattr(MyHandlers.handle_debit, _HANDLER_ATTR)
        assert isinstance(meta, HandlerMeta)
        assert meta.domain == "payments"
        assert meta.command_type == "DebitAccount"

    def test_multiple_handlers_in_class(self) -> None:
        """Test that multiple methods can be decorated in same class."""

        class PaymentHandlers:
            @handler(domain="payments", command_type="Debit")
            async def handle_debit(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

            @handler(domain="payments", command_type="Credit")
            async def handle_credit(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

        debit_meta = getattr(PaymentHandlers.handle_debit, _HANDLER_ATTR)
        credit_meta = getattr(PaymentHandlers.handle_credit, _HANDLER_ATTR)

        assert debit_meta.domain == "payments"
        assert debit_meta.command_type == "Debit"
        assert credit_meta.domain == "payments"
        assert credit_meta.command_type == "Credit"

    def test_handler_metadata_accessible(self) -> None:
        """Test that handler metadata can be retrieved."""

        class MyHandlers:
            @handler(domain="orders", command_type="PlaceOrder")
            async def handle_order(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

        meta = get_handler_meta(MyHandlers.handle_order)
        assert meta is not None
        assert meta.domain == "orders"
        assert meta.command_type == "PlaceOrder"

    def test_get_handler_meta_returns_none_for_undecorated(self) -> None:
        """Test that get_handler_meta returns None for undecorated methods."""

        class MyHandlers:
            async def regular_method(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

        meta = get_handler_meta(MyHandlers.regular_method)
        assert meta is None

    def test_decorator_preserves_function_identity(self) -> None:
        """Test that decorator preserves __name__ and __doc__."""

        class MyHandlers:
            @handler(domain="test", command_type="Test")
            async def my_handler(self, cmd: Command, ctx: HandlerContext) -> None:
                """My docstring."""
                pass

        assert MyHandlers.my_handler.__name__ == "my_handler"
        assert MyHandlers.my_handler.__doc__ == "My docstring."

    @pytest.mark.asyncio
    async def test_decorated_method_is_callable(self) -> None:
        """Test that decorated method can still be called."""

        class MyHandlers:
            @handler(domain="test", command_type="Test")
            async def handle(self, cmd: Command, ctx: HandlerContext) -> dict:
                return {"called": True}

        instance = MyHandlers()
        result = await instance.handle(None, None)  # type: ignore[arg-type]
        assert result == {"called": True}

    def test_handler_meta_is_frozen(self) -> None:
        """Test that HandlerMeta is immutable."""

        class MyHandlers:
            @handler(domain="payments", command_type="Debit")
            async def handle(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

        meta = getattr(MyHandlers.handle, _HANDLER_ATTR)

        with pytest.raises(AttributeError):
            meta.domain = "changed"  # type: ignore[misc]

    def test_different_domains_same_command_type(self) -> None:
        """Test handlers with same command type but different domains."""

        class Handlers:
            @handler(domain="payments", command_type="Process")
            async def handle_payments(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

            @handler(domain="orders", command_type="Process")
            async def handle_orders(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

        payments_meta = getattr(Handlers.handle_payments, _HANDLER_ATTR)
        orders_meta = getattr(Handlers.handle_orders, _HANDLER_ATTR)

        assert payments_meta.domain == "payments"
        assert orders_meta.domain == "orders"
        assert payments_meta.command_type == orders_meta.command_type == "Process"


class TestRegisterInstance:
    """Tests for register_instance method."""

    def test_register_instance_discovers_handlers(self) -> None:
        """Test that register_instance finds all decorated methods."""

        class PaymentHandlers:
            @handler(domain="payments", command_type="Debit")
            async def handle_debit(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

            @handler(domain="payments", command_type="Credit")
            async def handle_credit(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

        registry = HandlerRegistry()
        instance = PaymentHandlers()

        registered = registry.register_instance(instance)

        assert len(registered) == 2
        assert ("payments", "Debit") in registered
        assert ("payments", "Credit") in registered
        assert registry.has_handler("payments", "Debit")
        assert registry.has_handler("payments", "Credit")

    @pytest.mark.asyncio
    async def test_registered_handler_bound_to_instance(self) -> None:
        """Test that registered handler has access to instance state."""

        class PaymentHandlers:
            def __init__(self, service: AsyncMock) -> None:
                self._service = service

            @handler(domain="payments", command_type="Debit")
            async def handle_debit(self, cmd: Command, ctx: HandlerContext) -> dict:
                return await self._service.debit(cmd.data["amount"])

        mock_service = AsyncMock()
        mock_service.debit.return_value = {"balance": 100}

        registry = HandlerRegistry()
        instance = PaymentHandlers(mock_service)
        registry.register_instance(instance)

        cmd = Command(
            domain="payments",
            command_type="Debit",
            command_id=uuid4(),
            data={"amount": 50},
        )
        ctx = HandlerContext(command=cmd, attempt=1, max_attempts=3, msg_id=1)

        result = await registry.dispatch(cmd, ctx)

        mock_service.debit.assert_called_once_with(50)
        assert result == {"balance": 100}

    def test_register_instance_rejects_duplicate(self) -> None:
        """Test that duplicate handlers raise error."""

        class HandlersA:
            @handler(domain="payments", command_type="Debit")
            async def handle(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

        class HandlersB:
            @handler(domain="payments", command_type="Debit")
            async def handle(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

        registry = HandlerRegistry()
        registry.register_instance(HandlersA())

        with pytest.raises(HandlerAlreadyRegisteredError):
            registry.register_instance(HandlersB())

    def test_register_instance_empty_class(self) -> None:
        """Test that class with no handlers returns empty list."""

        class NoHandlers:
            def regular_method(self) -> None:
                pass

        registry = HandlerRegistry()
        registered = registry.register_instance(NoHandlers())

        assert registered == []

    def test_register_instance_skips_private_methods(self) -> None:
        """Test that private methods are not registered."""

        class Handlers:
            @handler(domain="test", command_type="Public")
            async def handle_public(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

            @handler(domain="test", command_type="Private")
            async def _handle_private(self, cmd: Command, ctx: HandlerContext) -> None:
                pass

        registry = HandlerRegistry()
        registered = registry.register_instance(Handlers())

        assert len(registered) == 1
        assert ("test", "Public") in registered
        assert ("test", "Private") not in registered
        assert not registry.has_handler("test", "Private")

    @pytest.mark.asyncio
    async def test_mixed_function_and_class_handlers(self) -> None:
        """Test that function and class handlers coexist."""

        class ClassHandlers:
            @handler(domain="orders", command_type="Create")
            async def handle_create(self, cmd: Command, ctx: HandlerContext) -> dict:
                return {"source": "class"}

        async def function_handler(cmd: Command, ctx: HandlerContext) -> dict:
            return {"source": "function"}

        registry = HandlerRegistry()
        registry.register("payments", "Debit", function_handler)
        registry.register_instance(ClassHandlers())

        # Dispatch to function handler
        cmd1 = Command(domain="payments", command_type="Debit", command_id=uuid4(), data={})
        ctx1 = HandlerContext(command=cmd1, attempt=1, max_attempts=3, msg_id=1)
        result1 = await registry.dispatch(cmd1, ctx1)
        assert result1 == {"source": "function"}

        # Dispatch to class handler
        cmd2 = Command(domain="orders", command_type="Create", command_id=uuid4(), data={})
        ctx2 = HandlerContext(command=cmd2, attempt=1, max_attempts=3, msg_id=2)
        result2 = await registry.dispatch(cmd2, ctx2)
        assert result2 == {"source": "class"}

    def test_register_instance_with_inheritance(self) -> None:
        """Test that inherited handlers are also discovered."""

        class BaseHandlers:
            @handler(domain="base", command_type="BaseCmd")
            async def handle_base(self, cmd: Command, ctx: HandlerContext) -> dict:
                return {"handler": "base"}

        class DerivedHandlers(BaseHandlers):
            @handler(domain="derived", command_type="DerivedCmd")
            async def handle_derived(self, cmd: Command, ctx: HandlerContext) -> dict:
                return {"handler": "derived"}

        registry = HandlerRegistry()
        instance = DerivedHandlers()

        registered = registry.register_instance(instance)

        assert len(registered) == 2
        assert ("base", "BaseCmd") in registered
        assert ("derived", "DerivedCmd") in registered

    @pytest.mark.asyncio
    async def test_register_instance_preserves_handler_functionality(self) -> None:
        """Test that the registered handler invokes the actual instance method."""
        call_tracker: list[str] = []

        class Handlers:
            def __init__(self, name: str) -> None:
                self.name = name

            @handler(domain="test", command_type="Test")
            async def handle(self, cmd: Command, ctx: HandlerContext) -> str:
                call_tracker.append(self.name)
                return f"handled by {self.name}"

        registry = HandlerRegistry()
        instance = Handlers("my_instance")
        registry.register_instance(instance)

        cmd = Command(domain="test", command_type="Test", command_id=uuid4(), data={})
        ctx = HandlerContext(command=cmd, attempt=1, max_attempts=3, msg_id=1)

        result = await registry.dispatch(cmd, ctx)

        assert result == "handled by my_instance"
        assert call_tracker == ["my_instance"]
