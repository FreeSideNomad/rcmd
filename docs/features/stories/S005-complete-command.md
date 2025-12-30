# S005: Complete Command Successfully

## Parent Feature

[F002 - Command Processing](../F002-command-processing.md)

## User Story

**As a** command handler
**I want** to mark a command as completed
**So that** the message is removed and a success reply is sent

## Context

When a handler successfully processes a command, it must be marked complete. This removes the message from the queue, updates metadata to COMPLETED, and sends a reply to the configured reply queue. All operations happen in a single transaction.

## Acceptance Criteria (Given-When-Then)

### Scenario: Complete a command successfully

**Given** a command is being processed by a handler
**And** the handler completes without error
**When** complete is called for the command
**Then** the PGMQ message is deleted
**And** command metadata status is updated to "COMPLETED"
**And** a reply message is sent to the reply queue
**And** the reply has outcome: "SUCCESS"
**And** an audit event "COMPLETED" is recorded

### Scenario: Complete with result data

**Given** a command is being processed
**When** complete is called with result_data: {"order_id": "xyz"}
**Then** the reply message includes data: {"order_id": "xyz"}

### Scenario: All operations are atomic

**Given** a command is being processed
**When** complete is called
**And** the reply queue send fails
**Then** the entire operation is rolled back
**And** the command remains in PENDING status
**And** the PGMQ message is NOT deleted

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Message deleted | Unit | `tests/unit/test_worker.py::test_complete_deletes_message` |
| Status updated | Unit | `tests/unit/test_worker.py::test_complete_updates_status` |
| Reply sent | Unit | `tests/unit/test_worker.py::test_complete_sends_reply` |
| Atomic rollback | Integration | `tests/integration/test_worker.py::test_complete_atomic` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- S004: Receive and process command

## Technical Notes

- Use `pgmq.delete(queue, msg_id)` to remove message
- Reply format defined in spec section 7.2
- Transaction must include: delete, status update, reply send, audit

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/worker.py` - Complete logic
- `src/commandbus/pgmq/client.py` - delete() and send()
- `docs/command-bus-python-spec.md` - Section 9.3

**Constraints:**
- Must be transactional with reply sending
- Reply queue comes from command metadata
- Handler result data is optional

**Verification Steps:**
1. Run `pytest tests/unit/test_worker.py::test_complete -v`
2. Run `pytest tests/integration/test_worker.py::test_complete -v`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
