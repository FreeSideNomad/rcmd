# S007: Run Worker with Concurrency

## Parent Feature

[F002 - Command Processing](../F002-command-processing.md)

## User Story

**As a** operations engineer
**I want** to run workers with configurable concurrency
**So that** I can process multiple commands in parallel for better throughput

## Context

A single worker processing one command at a time may not provide sufficient throughput. Workers should support concurrent processing of multiple commands while maintaining per-command guarantees. Graceful shutdown ensures in-flight commands complete.

## Acceptance Criteria (Given-When-Then)

### Scenario: Run worker with concurrency

**Given** a CommandBus with handlers registered
**When** I call run_worker with concurrency=5
**Then** up to 5 commands are processed concurrently
**And** the worker polls for new commands continuously

### Scenario: Graceful shutdown

**Given** a worker is running with 3 commands in-flight
**When** stop() is called
**Then** no new commands are received
**And** the 3 in-flight commands complete (or timeout)
**And** run_worker() returns cleanly

### Scenario: Use pg_notify for wake-up

**Given** a worker is running with use_notify=True
**And** the queue is empty
**When** a new command is sent to the queue
**Then** the worker wakes immediately via LISTEN notification
**And** the command is processed without waiting for poll interval

### Scenario: Fallback to polling

**Given** a worker is running with use_notify=True
**And** pg_notify is missed (edge case)
**When** poll_interval seconds elapse
**Then** the worker polls the queue
**And** any available commands are processed

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Concurrent processing | Integration | `tests/integration/test_worker.py::test_concurrent_processing` |
| Graceful shutdown | Integration | `tests/integration/test_worker.py::test_graceful_shutdown` |
| Notify wake-up | Integration | `tests/integration/test_worker.py::test_notify_wakeup` |
| Poll fallback | Integration | `tests/integration/test_worker.py::test_poll_fallback` |

## Story Size

M (2000-5000 tokens, module implementation)

## Priority (MoSCoW)

Must Have

## Dependencies

- S004: Receive and process command
- S005: Complete command successfully
- S006: Register command handler

## Technical Notes

- Use `asyncio.TaskGroup` for concurrent workers (Python 3.11+)
- Use `asyncio.Event` for shutdown signaling
- LISTEN channel: `commandbus.<domain>`
- Poll interval default: 5 seconds

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/worker.py` - Worker class
- `src/commandbus/pgmq/notify.py` - LISTEN implementation
- `docs/command-bus-python-spec.md` - Section 10, 11

**Constraints:**
- Must handle `asyncio.CancelledError` for shutdown
- Must not lose messages on shutdown (VT will handle redelivery)
- Poll interval is fallback, not primary mechanism

**Verification Steps:**
1. Run `pytest tests/integration/test_worker.py -v`
2. Test manual shutdown with Ctrl+C

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
