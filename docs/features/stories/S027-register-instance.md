# S027: Discover Handlers via register_instance()

## Parent Feature

[F007 - Handler Dependency Injection](../F007-handler-dependency-injection.md)

## User Story

**As a** application developer
**I want** to register a handler class instance with the registry
**So that** all @handler decorated methods are automatically discovered and registered

## Context

After decorating methods with `@handler`, the developer instantiates the handler class (with dependencies) and registers it with the HandlerRegistry. The registry scans the instance for decorated methods and registers each one.

This enables the composition root pattern where dependencies are wired manually and handler classes are registered in one call.

## Acceptance Criteria (Given-When-Then)

### Scenario: Discover handlers from instance

**Given** a class with methods decorated with `@handler`
**When** I call `registry.register_instance(instance)`
**Then** all decorated methods are registered with the registry
**And** the returned list contains all registered (domain, command_type) pairs

### Scenario: Handlers are bound to instance

**Given** a handler class with `self._service` dependency
**When** the handler method is dispatched
**Then** it executes with access to `self._service`
**And** the instance's state is preserved

### Scenario: Duplicate handler in instance rejected

**Given** a handler is already registered for "payments.Debit"
**When** I register an instance with another method for "payments.Debit"
**Then** `HandlerAlreadyRegisteredError` is raised
**And** no handlers from that instance are registered

### Scenario: Empty instance returns empty list

**Given** a class with no @handler decorated methods
**When** I call `registry.register_instance(instance)`
**Then** an empty list is returned
**And** no error is raised

### Scenario: Private methods are skipped

**Given** a class with `@handler` on a method named `_handle_internal`
**When** I call `registry.register_instance(instance)`
**Then** the private method is skipped
**And** a warning is logged (optional)

### Scenario: Mix with direct registration

**Given** I have registered function handlers directly
**When** I also call `register_instance()` with class handlers
**Then** both function and class handlers coexist in registry
**And** dispatch works for both types

## Technical Design

```python
class HandlerRegistry:
    def register_instance(self, instance: object) -> list[tuple[str, str]]:
        """Scan instance for @handler decorated methods and register them.

        Args:
            instance: An object instance with @handler decorated methods

        Returns:
            List of (domain, command_type) tuples that were registered

        Raises:
            HandlerAlreadyRegisteredError: If any handler is already registered
        """
        registered: list[tuple[str, str]] = []

        for name in dir(instance):
            if name.startswith("_"):
                continue

            method = getattr(instance, name)
            if not callable(method):
                continue

            meta = getattr(method, _HANDLER_ATTR, None)
            if meta is None:
                continue

            if not isinstance(meta, HandlerMeta):
                continue

            self.register(meta.domain, meta.command_type, method)
            registered.append((meta.domain, meta.command_type))
            logger.info(
                f"Discovered handler {instance.__class__.__name__}.{name} "
                f"for {meta.domain}.{meta.command_type}"
            )

        return registered
```

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Discover handlers | Unit | `tests/unit/test_handler.py::test_register_instance_discovers_handlers` |
| Handlers bound to instance | Unit | `tests/unit/test_handler.py::test_registered_handler_bound_to_instance` |
| Duplicate rejected | Unit | `tests/unit/test_handler.py::test_register_instance_rejects_duplicate` |
| Empty instance | Unit | `tests/unit/test_handler.py::test_register_instance_empty_class` |
| Private methods skipped | Unit | `tests/unit/test_handler.py::test_register_instance_skips_private` |
| Mix with direct | Unit | `tests/unit/test_handler.py::test_mixed_function_and_class_handlers` |

## Example Test

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from commandbus import Command, HandlerContext, HandlerRegistry
from commandbus.handler import handler
from commandbus.exceptions import HandlerAlreadyRegisteredError


class TestRegisterInstance:
    def test_register_instance_discovers_handlers(self):
        """Test that register_instance finds all decorated methods."""
        class PaymentHandlers:
            @handler(domain="payments", command_type="Debit")
            async def handle_debit(self, cmd, ctx):
                pass

            @handler(domain="payments", command_type="Credit")
            async def handle_credit(self, cmd, ctx):
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
    async def test_registered_handler_bound_to_instance(self):
        """Test that registered handler has access to instance state."""
        class PaymentHandlers:
            def __init__(self, service):
                self._service = service

            @handler(domain="payments", command_type="Debit")
            async def handle_debit(self, cmd, ctx):
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
        ctx = MagicMock(spec=HandlerContext)

        result = await registry.dispatch(cmd, ctx)

        mock_service.debit.assert_called_once_with(50)
        assert result == {"balance": 100}

    def test_register_instance_rejects_duplicate(self):
        """Test that duplicate handlers raise error."""
        class HandlersA:
            @handler(domain="payments", command_type="Debit")
            async def handle(self, cmd, ctx):
                pass

        class HandlersB:
            @handler(domain="payments", command_type="Debit")
            async def handle(self, cmd, ctx):
                pass

        registry = HandlerRegistry()
        registry.register_instance(HandlersA())

        with pytest.raises(HandlerAlreadyRegisteredError):
            registry.register_instance(HandlersB())

    def test_register_instance_empty_class(self):
        """Test that class with no handlers returns empty list."""
        class NoHandlers:
            def regular_method(self):
                pass

        registry = HandlerRegistry()
        registered = registry.register_instance(NoHandlers())

        assert registered == []

    def test_register_instance_skips_private_methods(self):
        """Test that private methods are not registered."""
        class Handlers:
            @handler(domain="test", command_type="Public")
            async def handle_public(self, cmd, ctx):
                pass

            @handler(domain="test", command_type="Private")
            async def _handle_private(self, cmd, ctx):
                pass

        registry = HandlerRegistry()
        registered = registry.register_instance(Handlers())

        assert len(registered) == 1
        assert ("test", "Public") in registered
        assert ("test", "Private") not in registered

    @pytest.mark.asyncio
    async def test_mixed_function_and_class_handlers(self):
        """Test that function and class handlers coexist."""
        class ClassHandlers:
            @handler(domain="orders", command_type="Create")
            async def handle_create(self, cmd, ctx):
                return {"source": "class"}

        async def function_handler(cmd, ctx):
            return {"source": "function"}

        registry = HandlerRegistry()
        registry.register("payments", "Debit", function_handler)
        registry.register_instance(ClassHandlers())

        # Dispatch to function handler
        cmd1 = Command(domain="payments", command_type="Debit", command_id=uuid4(), data={})
        result1 = await registry.dispatch(cmd1, MagicMock())
        assert result1 == {"source": "function"}

        # Dispatch to class handler
        cmd2 = Command(domain="orders", command_type="Create", command_id=uuid4(), data={})
        result2 = await registry.dispatch(cmd2, MagicMock())
        assert result2 == {"source": "class"}
```

## Story Size

M (2000-4000 tokens, medium feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- [S026](S026-handler-decorator-class.md) - @handler decorator must exist

## Technical Notes

- Uses `dir()` to iterate instance members (includes inherited)
- Skips names starting with `_` (private/dunder)
- `getattr(method, _HANDLER_ATTR, None)` safely checks for metadata
- Bound methods automatically capture `self`
- Order of discovery is not guaranteed (use explicit ordering if needed)

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/handler.py` - Add register_instance() method

**Constraints:**
- Must work with inheritance (methods from base class)
- Must not register non-callable attributes
- Must maintain backwards compatibility with register()

**Verification Steps:**
1. Run `pytest tests/unit/test_handler.py -v -k register_instance`
2. Run `make typecheck`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration test with worker dispatch
- [ ] Acceptance criteria verified
- [ ] No regressions in existing handler tests
