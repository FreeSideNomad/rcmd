# S008: Automatic Retry on Transient Failure

## Parent Feature

[F003 - Retry & Error Handling](../F003-retry-error-handling.md)

## User Story

**As a** command handler developer
**I want** transient failures to be automatically retried
**So that** temporary issues don't require manual intervention

## Context

Transient failures (network timeouts, temporary unavailability, rate limits) are expected in distributed systems. The Command Bus should automatically retry these failures using visibility timeout expiry, with configurable backoff between attempts.

## Acceptance Criteria (Given-When-Then)

### Scenario: Transient error triggers retry

**Given** a handler is processing a command (attempt 1 of 3)
**When** the handler raises `TransientCommandError`
**Then** the command metadata attempts is updated to 1
**And** the last_error fields are populated
**And** the PGMQ message is NOT deleted (left to expire)
**And** an audit event "FAILED" with type "TRANSIENT" is recorded
**And** no reply is sent

### Scenario: Message reappears after visibility timeout

**Given** a command failed with TransientCommandError
**And** the visibility timeout was 30 seconds
**When** 30 seconds elapse
**Then** the message becomes visible again
**And** another worker can receive and retry it

### Scenario: Backoff increases visibility timeout

**Given** a command has failed once (attempt 1)
**And** backoff schedule is [10, 60, 300]
**When** the retry policy is applied
**Then** the visibility timeout for next attempt is 60 seconds
**And** attempt 3 would have VT of 300 seconds

### Scenario: Unknown exceptions treated as transient

**Given** a handler raises `ValueError` (not a CommandBus exception)
**When** the worker catches the exception
**Then** it is treated as TransientCommandError
**And** the command is retried according to policy

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Transient updates metadata | Unit | `tests/unit/test_worker.py::test_transient_error_updates_metadata` |
| Message not deleted | Unit | `tests/unit/test_worker.py::test_transient_error_leaves_message` |
| VT redelivery | Integration | `tests/integration/test_retry.py::test_transient_retry_flow` |
| Backoff applied | Unit | `tests/unit/test_policies.py::test_backoff_schedule` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- S004: Receive and process command
- S006: Register command handler

## Technical Notes

- Retry uses VT expiry, not re-queue (avoids message duplication)
- Backoff is applied via `pgmq.set_vt()` after failure
- Default: max_attempts=3, backoff=[10, 60, 300]

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/worker.py` - Error handling
- `src/commandbus/exceptions.py` - TransientCommandError
- `src/commandbus/policies.py` - RetryPolicy, backoff calculation
- `docs/command-bus-python-spec.md` - Section 4.3

**Constraints:**
- Must update metadata before releasing message
- Must use `set_vt()` to apply backoff delay
- Unknown exceptions → TransientCommandError

**Verification Steps:**
1. Run `pytest tests/unit/test_worker.py::test_transient -v`
2. Run `pytest tests/integration/test_retry.py -v`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
