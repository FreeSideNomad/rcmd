# S004: Receive and Process Command

## Parent Feature

[F002 - Command Processing](../F002-command-processing.md)

## User Story

**As a** worker process
**I want** to receive commands from a domain queue
**So that** I can process them with guaranteed at-least-once delivery

## Context

Workers poll PGMQ queues to receive commands. When a message is read, it becomes invisible to other workers for the visibility timeout period. If the worker crashes or doesn't acknowledge, the message reappears for retry. This provides at-least-once delivery semantics.

## Acceptance Criteria (Given-When-Then)

### Scenario: Receive a pending command

**Given** a command exists in the "payments__commands" queue
**And** no worker has leased it
**When** the worker calls receive with vt=30 seconds
**Then** the command message is returned
**And** the message is invisible to other workers for 30 seconds
**And** command metadata attempts is incremented
**And** an audit event "RECEIVED" is recorded

### Scenario: No commands available

**Given** the "payments__commands" queue is empty
**When** the worker calls receive
**Then** an empty list is returned
**And** no error is raised

### Scenario: Message reappears after visibility timeout

**Given** a worker received a command with vt=5 seconds
**And** the worker did not acknowledge (complete/cancel)
**And** 5 seconds have passed
**When** another worker calls receive
**Then** the same command is returned
**And** attempts count is incremented again

### Scenario: Skip terminal commands

**Given** a message exists in the queue
**But** the command metadata shows status "COMPLETED"
**When** the worker receives the message
**Then** the message is archived (cleaned up)
**And** the worker continues to the next message

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Receive returns command | Unit | `tests/unit/test_worker.py::test_receive_returns_command` |
| Empty queue returns empty | Unit | `tests/unit/test_worker.py::test_receive_empty_queue` |
| Attempts incremented | Unit | `tests/unit/test_worker.py::test_receive_increments_attempts` |
| VT redelivery | Integration | `tests/integration/test_worker.py::test_vt_redelivery` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- S001: Send a command (commands must exist)
- PGMQ queue created

## Technical Notes

- Use `pgmq.read(queue, vt, limit)` for message retrieval
- Parse message to get command_id, then lookup metadata
- Handle orphaned messages (no metadata) gracefully
- Consider pg_notify/LISTEN for wake-on-message (S007)

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/worker.py` - Receive logic
- `src/commandbus/pgmq/client.py` - PgmqClient.read()
- `docs/command-bus-python-spec.md` - Section 9.2

**Constraints:**
- Must update attempts before dispatching to handler
- Must handle case where metadata doesn't exist
- VT should be configurable

**Verification Steps:**
1. Run `pytest tests/unit/test_worker.py::test_receive -v`
2. Run `pytest tests/integration/test_worker.py -v`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
