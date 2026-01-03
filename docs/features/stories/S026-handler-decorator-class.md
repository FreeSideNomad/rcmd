# S026: Use @handler Decorator on Class Methods

## Parent Feature

[F007 - Handler Dependency Injection](../F007-handler-dependency-injection.md)

## User Story

**As a** application developer
**I want** to use @handler decorator on class methods
**So that** I can organize handlers in classes with injected dependencies

## Context

Currently handlers are plain functions registered via `@registry.handler()` or `registry.register()`. This story adds support for decorating methods within handler classes, enabling dependency injection via constructor.

The decorator marks methods with metadata that is later discovered by `register_instance()`.

## Acceptance Criteria (Given-When-Then)

### Scenario: Decorate class method as handler

**Given** a handler class with a method
**When** I apply `@handler(domain="payments", command_type="DebitAccount")`
**Then** the method is marked with handler metadata
**And** the method remains callable as normal
**And** the method's signature is unchanged

### Scenario: Multiple handlers in same class

**Given** a handler class
**When** I decorate multiple methods with `@handler`
**Then** each method has its own domain/command_type metadata
**And** all methods are marked for discovery

### Scenario: Handler metadata is accessible

**Given** a method decorated with `@handler(domain="x", command_type="Y")`
**When** I inspect the method for handler metadata
**Then** I can retrieve domain="x" and command_type="Y"

### Scenario: Decorator preserves function identity

**Given** a decorated handler method
**When** I access `__name__`, `__doc__`, `__module__`
**Then** they reflect the original function, not the decorator

## Technical Design

```python
from dataclasses import dataclass
from typing import Callable

_HANDLER_ATTR = "_commandbus_handler_meta"

@dataclass(frozen=True)
class HandlerMeta:
    """Metadata attached to decorated handler methods."""
    domain: str
    command_type: str

def handler(domain: str, command_type: str) -> Callable[[Callable], Callable]:
    """Decorator to mark a method as a command handler.

    Args:
        domain: The domain (e.g., "payments")
        command_type: The command type (e.g., "DebitAccount")

    Example:
        class PaymentHandlers:
            @handler(domain="payments", command_type="DebitAccount")
            async def handle_debit(self, cmd: Command, ctx: HandlerContext) -> dict:
                ...
    """
    def decorator(fn: Callable) -> Callable:
        setattr(fn, _HANDLER_ATTR, HandlerMeta(domain=domain, command_type=command_type))
        return fn
    return decorator
```

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Method marked with metadata | Unit | `tests/unit/test_handler.py::test_handler_decorator_sets_metadata` |
| Multiple handlers in class | Unit | `tests/unit/test_handler.py::test_multiple_handlers_in_class` |
| Metadata accessible | Unit | `tests/unit/test_handler.py::test_handler_metadata_accessible` |
| Function identity preserved | Unit | `tests/unit/test_handler.py::test_decorator_preserves_function_identity` |

## Example Test

```python
import pytest
from commandbus.handler import handler, HandlerMeta, _HANDLER_ATTR

class TestHandlerDecorator:
    def test_handler_decorator_sets_metadata(self):
        """Test that @handler decorator attaches metadata to method."""
        class MyHandlers:
            @handler(domain="payments", command_type="DebitAccount")
            async def handle_debit(self, cmd, ctx):
                return {"status": "ok"}

        meta = getattr(MyHandlers.handle_debit, _HANDLER_ATTR)
        assert isinstance(meta, HandlerMeta)
        assert meta.domain == "payments"
        assert meta.command_type == "DebitAccount"

    def test_multiple_handlers_in_class(self):
        """Test that multiple methods can be decorated in same class."""
        class PaymentHandlers:
            @handler(domain="payments", command_type="Debit")
            async def handle_debit(self, cmd, ctx):
                pass

            @handler(domain="payments", command_type="Credit")
            async def handle_credit(self, cmd, ctx):
                pass

        debit_meta = getattr(PaymentHandlers.handle_debit, _HANDLER_ATTR)
        credit_meta = getattr(PaymentHandlers.handle_credit, _HANDLER_ATTR)

        assert debit_meta.command_type == "Debit"
        assert credit_meta.command_type == "Credit"

    def test_decorator_preserves_function_identity(self):
        """Test that decorator preserves __name__ and __doc__."""
        class MyHandlers:
            @handler(domain="test", command_type="Test")
            async def my_handler(self, cmd, ctx):
                """My docstring."""
                pass

        assert MyHandlers.my_handler.__name__ == "my_handler"
        assert MyHandlers.my_handler.__doc__ == "My docstring."

    @pytest.mark.asyncio
    async def test_decorated_method_is_callable(self):
        """Test that decorated method can still be called."""
        class MyHandlers:
            @handler(domain="test", command_type="Test")
            async def handle(self, cmd, ctx):
                return {"called": True}

        instance = MyHandlers()
        result = await instance.handle(None, None)
        assert result == {"called": True}
```

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- None (foundational for F007)

## Technical Notes

- Decorator uses `setattr` to attach metadata, avoiding wrapper functions
- `functools.wraps` not needed since we return the original function
- Metadata is a frozen dataclass for immutability
- Attribute name uses underscore prefix to indicate internal use

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/handler.py` - Add decorator and HandlerMeta

**Constraints:**
- Must not change function signature or behavior
- Must work with both sync and async methods
- Metadata must be retrievable after decoration

**Verification Steps:**
1. Run `pytest tests/unit/test_handler.py -v -k decorator`
2. Run `make typecheck`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Decorator exported from `commandbus` package
- [ ] Acceptance criteria verified
- [ ] No regressions in related functionality
