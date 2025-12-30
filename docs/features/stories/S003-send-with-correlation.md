# S003: Send with Correlation ID

## Parent Feature

[F001 - Command Sending](../F001-command-sending.md)

## User Story

**As a** application developer
**I want** to include a correlation ID when sending commands
**So that** I can trace related commands and replies across the system

## Context

In distributed systems, a single user action may trigger multiple commands. A correlation ID groups these related commands for tracing and debugging. If not provided, the Command Bus generates one. The correlation ID is included in replies for request/response correlation.

## Acceptance Criteria (Given-When-Then)

### Scenario: Send with explicit correlation ID

**Given** the Command Bus is connected
**When** I send a command with correlation_id: "trace-xyz-789"
**Then** the correlation_id is stored in command metadata
**And** the message payload includes correlation_id: "trace-xyz-789"
**And** the audit event includes the correlation_id in details

### Scenario: Send without correlation ID generates one

**Given** the Command Bus is connected
**When** I send a command without specifying correlation_id
**Then** a new UUID is generated as correlation_id
**And** the generated ID is stored in metadata
**And** the generated ID is included in the message payload

### Scenario: Correlation ID included in reply

**Given** a command was sent with correlation_id: "trace-xyz-789"
**And** the command is processed successfully
**When** the reply message is sent
**Then** the reply payload includes correlation_id: "trace-xyz-789"

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Explicit correlation stored | Unit | `tests/unit/test_api.py::test_send_with_correlation_id` |
| Auto-generated when missing | Unit | `tests/unit/test_api.py::test_send_generates_correlation_id` |
| Included in payload | Unit | `tests/unit/test_api.py::test_correlation_id_in_payload` |
| Included in reply | Integration | `tests/integration/test_reply.py::test_reply_has_correlation_id` |

## Story Size

XS (< 500 tokens, single function)

## Priority (MoSCoW)

Should Have

## Dependencies

- S001: Send a command

## Technical Notes

- Use `uuid4()` if correlation_id not provided
- Store in both `command_bus_command.correlation_id` and message body
- Structured logging should include correlation_id in context

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/api.py` - send() method
- `src/commandbus/models.py` - Command model with correlation_id
- `docs/command-bus-python-spec.md` - Section 7.1, 7.2 envelope formats

**Constraints:**
- correlation_id must be UUID type
- Must appear in both metadata table and message body
- Reply must include same correlation_id

**Verification Steps:**
1. Run `pytest tests/unit/test_api.py::test_correlation -v`
2. Verify message payload structure

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
