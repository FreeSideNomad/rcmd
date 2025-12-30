# S011: List Commands in Troubleshooting

## Parent Feature

[F004 - Troubleshooting Queue](../F004-troubleshooting-queue.md)

## User Story

**As an** operator
**I want** to list commands in the troubleshooting queue
**So that** I can see what needs attention and investigate issues

## Context

The troubleshooting queue contains commands that failed permanently or exhausted retries. Operators need to view these commands with full context to decide on resolution: retry, cancel, or manual completion.

## Acceptance Criteria (Given-When-Then)

### Scenario: List all troubleshooting commands for a domain

**Given** 5 commands are in troubleshooting for domain "payments"
**And** 3 commands are in troubleshooting for domain "reports"
**When** I call list_troubleshooting(domain="payments")
**Then** 5 commands are returned
**And** each includes: command_id, command_type, attempts, last_error, created_at

### Scenario: Filter by command type

**Given** 3 DebitAccount and 2 CreditAccount commands in troubleshooting
**When** I call list_troubleshooting(domain="payments", command_type="DebitAccount")
**Then** only 3 DebitAccount commands are returned

### Scenario: Pagination

**Given** 150 commands are in troubleshooting for domain "payments"
**When** I call list_troubleshooting(limit=50, offset=0)
**Then** the first 50 commands are returned
**When** I call list_troubleshooting(limit=50, offset=50)
**Then** commands 51-100 are returned

### Scenario: Include archived payload

**Given** a command is in troubleshooting
**And** its payload was archived via pgmq.archive()
**When** I retrieve the troubleshooting item
**Then** the payload field contains the original command data

### Scenario: Empty troubleshooting queue

**Given** no commands are in troubleshooting for domain "reports"
**When** I call list_troubleshooting(domain="reports")
**Then** an empty list is returned

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| List returns items | Unit | `tests/unit/test_ops.py::test_list_troubleshooting` |
| Filter by type | Unit | `tests/unit/test_ops.py::test_list_filter_by_type` |
| Pagination | Unit | `tests/unit/test_ops.py::test_list_pagination` |
| Payload retrieval | Integration | `tests/integration/test_ops.py::test_payload_from_archive` |

## Story Size

S (500-2000 tokens, small feature)

## Priority (MoSCoW)

Must Have

## Dependencies

- S009: Handle permanent failure (creates TSQ entries)
- S010: Handle retry exhaustion (creates TSQ entries)

## Technical Notes

- Query `command_bus_command WHERE status = 'IN_TROUBLESHOOTING_QUEUE'`
- Payload from PGMQ archive table: `pgmq.a_<queue_name>`
- Order by created_at DESC (newest first)

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/ops/troubleshooting.py` - list_troubleshooting()
- `src/commandbus/repositories/postgres.py` - Query methods

**Constraints:**
- Must join with PGMQ archive for payload
- Paginate all responses
- Return TroubleshootingItem dataclass

**Verification Steps:**
1. Run `pytest tests/unit/test_ops.py::test_list -v`
2. Run `pytest tests/integration/test_ops.py -v`

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
