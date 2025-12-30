# S009: Handle Permanent Failure

## Parent Feature

[F003 - Retry & Error Handling](../F003-retry-error-handling.md)

## User Story

**As a** command handler developer
**I want** permanent failures to go directly to troubleshooting
**So that** invalid commands don't waste retry attempts

## Context

Permanent failures (validation errors, business rule violations, missing data) cannot be resolved by retrying. These should immediately move to the troubleshooting queue for operator review, without consuming retry attempts.

## Acceptance Criteria (Given-When-Then)

### Scenario: Permanent error moves to troubleshooting

**Given** a handler is processing a command
**When** the handler raises `PermanentCommandError`
**Then** the PGMQ message is archived (not deleted)
**And** command metadata status is set to "IN_TROUBLESHOOTING_QUEUE"
**And** last_error fields are populated with error details
**And** an audit event "MOVED_TO_TROUBLESHOOTING_QUEUE" is recorded
**And** no reply is sent automatically

### Scenario: Error details are captured

**Given** a handler raises `PermanentCommandError(code="INVALID_ACCOUNT", message="Account not found", details={"account_id": "xyz"})`
**When** the error is handled
**Then** metadata has last_error_code="INVALID_ACCOUNT"
**And** metadata has last_error_msg="Account not found"
**And** audit details include the full error info

### Scenario: First attempt permanent failure

**Given** a command is on its first attempt
**When** the handler raises PermanentCommandError
**Then** attempts is set to 1
**And** the command goes directly to troubleshooting
**And** no retry occurs

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Message archived | Unit | `tests/unit/test_worker.py::test_permanent_error_archives_message` |
| Status updated | Unit | `tests/unit/test_worker.py::test_permanent_error_sets_tsq_status` |
| Error details stored | Unit | `tests/unit/test_worker.py::test_permanent_error_stores_details` |
| Full flow | Integration | `tests/integration/test_retry.py::test_permanent_failure_flow` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- S004: Receive and process command
- S006: Register command handler

## Technical Notes

- Use `pgmq.archive()` to preserve payload for troubleshooting
- No reply sent until operator resolves
- max_attempts is effectively 1 for permanent errors

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/worker.py` - Permanent error handling
- `src/commandbus/exceptions.py` - PermanentCommandError
- `docs/command-bus-python-spec.md` - Section 4.3, 9.4

**Constraints:**
- Must archive message (not delete)
- Must capture full error details
- No automatic reply

**Verification Steps:**
1. Run `pytest tests/unit/test_worker.py::test_permanent -v`
2. Run `pytest tests/integration/test_retry.py::test_permanent -v`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
