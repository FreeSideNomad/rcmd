# S002: Idempotent Command Sending

## Parent Feature

[F001 - Command Sending](../F001-command-sending.md)

## User Story

**As a** application developer
**I want** duplicate command sends to be rejected
**So that** commands are processed exactly once even if my application retries

## Context

Network issues or application crashes may cause the same command to be sent multiple times. The Command Bus must enforce uniqueness of `command_id` within a domain to prevent duplicate processing. The client supplies the `command_id` as an idempotency key.

## Acceptance Criteria (Given-When-Then)

### Scenario: Reject duplicate command_id in same domain

**Given** a command with command_id "abc-123" exists in domain "payments"
**When** I send another command with command_id "abc-123" to domain "payments"
**Then** a `DuplicateCommandError` is raised
**And** the error includes the command_id
**And** no new message is sent to PGMQ
**And** no duplicate metadata row is created

### Scenario: Allow same command_id in different domains

**Given** a command with command_id "abc-123" exists in domain "payments"
**When** I send a command with command_id "abc-123" to domain "reports"
**Then** the command is accepted
**And** a new row is created for the "reports" domain

### Scenario: Idempotent retry returns same result

**Given** a command with command_id "abc-123" exists in domain "payments"
**And** the command has status "COMPLETED"
**When** I try to send with command_id "abc-123" to domain "payments"
**Then** a `DuplicateCommandError` is raised
**And** the client can query the existing command status

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Duplicate rejected | Unit | `tests/unit/test_api.py::test_send_duplicate_raises_error` |
| Different domain allowed | Unit | `tests/unit/test_api.py::test_send_same_id_different_domain` |
| Error includes command_id | Unit | `tests/unit/test_api.py::test_duplicate_error_contains_id` |
| Integration duplicate | Integration | `tests/integration/test_send.py::test_duplicate_rejected` |

## Story Size

XS (< 500 tokens, single function)

## Priority (MoSCoW)

Must Have

## Dependencies

- S001: Send a command (base send functionality)

## Technical Notes

- Uniqueness enforced by: `UNIQUE INDEX (domain, command_id)`
- Catch `psycopg.errors.UniqueViolation` and wrap in `DuplicateCommandError`
- Check must happen in the transaction before PGMQ send

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/api.py` - Error handling in send()
- `src/commandbus/exceptions.py` - DuplicateCommandError
- `scripts/init-db.sql` - Unique index definition

**Constraints:**
- Must catch database unique violation
- Must not send to PGMQ if duplicate
- Error must include command_id for client debugging

**Verification Steps:**
1. Run `pytest tests/unit/test_api.py::test_duplicate -v`
2. Verify unique index exists in database

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
