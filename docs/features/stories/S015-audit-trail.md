# S015: Audit Trail for Commands

## Parent Feature

[F005 - Observability & Audit](../F005-observability.md)

## User Story

**As a** developer or operator
**I want** to view the audit trail for a command
**So that** I can trace its lifecycle and debug issues

## Context

Every state transition in a command's lifecycle is recorded in the audit table. This provides a complete history for debugging, compliance, and operational visibility.

## Acceptance Criteria (Given-When-Then)

### Scenario: Get audit trail for a command

**Given** a command was sent, received, failed, and completed via operator
**When** I call get_audit_trail(command_id="abc-123")
**Then** a list of audit events is returned in chronological order
**And** events include: SENT, RECEIVED, FAILED, MOVED_TO_TROUBLESHOOTING_QUEUE, OPERATOR_COMPLETE

### Scenario: Audit event details

**Given** a command failed with TransientCommandError
**When** I view the FAILED audit event
**Then** details include: error_type="TRANSIENT", code, message

### Scenario: Audit includes timestamps

**Given** a command has audit events
**When** I retrieve the audit trail
**Then** each event has a timestamp
**And** events are ordered by timestamp ascending

### Scenario: Command with no audit

**Given** no command exists with command_id "xyz-999"
**When** I call get_audit_trail(command_id="xyz-999")
**Then** an empty list is returned

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Events returned | Unit | `tests/unit/test_repos.py::test_get_audit_trail` |
| Chronological order | Unit | `tests/unit/test_repos.py::test_audit_order` |
| Details included | Unit | `tests/unit/test_repos.py::test_audit_details` |
| Full lifecycle | Integration | `tests/integration/test_audit.py::test_full_lifecycle_audit` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Should Have

## Dependencies

- All features that record audit events

## Technical Notes

- Query `command_bus_audit WHERE command_id = ? ORDER BY ts ASC`
- details_json is optional JSONB column
- Return list of AuditEvent dataclass

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/api.py` - get_audit_trail()
- `src/commandbus/repositories/postgres.py` - Audit query

**Constraints:**
- Order by timestamp ascending
- Parse JSONB details into dict
- Return empty list for unknown command

**Verification Steps:**
1. Run `pytest tests/unit/test_repos.py::test_audit -v`
2. Run `pytest tests/integration/test_audit.py -v`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
