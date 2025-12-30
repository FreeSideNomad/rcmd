# S006: Register Command Handler

## Parent Feature

[F002 - Command Processing](../F002-command-processing.md)

## User Story

**As a** application developer
**I want** to register handlers for specific command types
**So that** the worker dispatches commands to the correct processing logic

## Context

Different command types require different processing logic. Developers register handler functions that are called when a matching command is received. The registry maps (domain, command_type) to handler functions.

## Acceptance Criteria (Given-When-Then)

### Scenario: Register a handler function

**Given** a CommandBus instance
**When** I register a handler for domain "payments" and type "DebitAccount"
**Then** the handler is stored in the registry
**And** no error is raised

### Scenario: Dispatch to registered handler

**Given** a handler is registered for "payments.DebitAccount"
**When** a command with domain "payments" and type "DebitAccount" is received
**Then** the registered handler is called with the command and context
**And** the handler receives the command data

### Scenario: Reject duplicate handler registration

**Given** a handler is already registered for "payments.DebitAccount"
**When** I try to register another handler for "payments.DebitAccount"
**Then** a `HandlerAlreadyRegisteredError` is raised
**And** the original handler is preserved

### Scenario: No handler registered for command type

**Given** no handler is registered for "payments.RefundPayment"
**When** a command with type "RefundPayment" is received
**Then** a warning is logged
**And** the message is archived (not retried)
**And** the command moves to troubleshooting queue

### Scenario: Use decorator for registration

**Given** a CommandBus instance
**When** I use the @command_bus.handler decorator
**Then** the decorated function is registered
**And** the function is returned unchanged

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Handler stored | Unit | `tests/unit/test_handler.py::test_register_handler` |
| Dispatch works | Unit | `tests/unit/test_handler.py::test_dispatch_to_handler` |
| Duplicate rejected | Unit | `tests/unit/test_handler.py::test_duplicate_handler_error` |
| Missing handler | Unit | `tests/unit/test_handler.py::test_no_handler_logs_warning` |
| Decorator works | Unit | `tests/unit/test_handler.py::test_handler_decorator` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- None (foundational)

## Technical Notes

- Handler signature: `async def handler(command: Command, context: HandlerContext) -> Any`
- HandlerContext provides: extend_visibility(), command metadata
- Registry is a dict: `dict[tuple[str, str], HandlerFn]`

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/handler.py` - HandlerRegistry class
- `src/commandbus/models.py` - Command, HandlerContext

**Constraints:**
- Handlers must be async functions
- One handler per (domain, command_type) pair
- Context provides VT extension for long operations

**Verification Steps:**
1. Run `pytest tests/unit/test_handler.py -v`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
