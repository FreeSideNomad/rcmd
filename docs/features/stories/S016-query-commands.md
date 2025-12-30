# S016: Query Commands by Status

## Parent Feature

[F005 - Observability & Audit](../F005-observability.md)

## User Story

**As an** operator
**I want** to query commands by various filters
**So that** I can monitor system health and find specific commands

## Context

Operators need to answer questions like "How many commands are pending?", "What failed in the last hour?", "Show me all DebitAccount commands". A flexible query API supports these operational needs.

## Acceptance Criteria (Given-When-Then)

### Scenario: Query by status

**Given** 10 PENDING, 5 IN_PROGRESS, and 20 COMPLETED commands exist
**When** I call query_commands(status=PENDING)
**Then** 10 commands are returned
**And** all have status="PENDING"

### Scenario: Query by domain and type

**Given** commands exist for multiple domains and types
**When** I call query_commands(domain="payments", command_type="DebitAccount")
**Then** only payments.DebitAccount commands are returned

### Scenario: Query by date range

**Given** commands created at various times
**When** I call query_commands(created_after="2024-01-01", created_before="2024-01-31")
**Then** only commands created in January are returned

### Scenario: Combine multiple filters

**Given** various commands exist
**When** I call query_commands(domain="payments", status=PENDING, command_type="DebitAccount")
**Then** only commands matching ALL criteria are returned

### Scenario: Pagination

**Given** 200 PENDING commands exist
**When** I call query_commands(status=PENDING, limit=50, offset=50)
**Then** commands 51-100 are returned
**And** results are ordered by created_at descending

### Scenario: Get single command

**Given** a command exists with command_id "abc-123"
**When** I call get_command(domain="payments", command_id="abc-123")
**Then** the full command metadata is returned

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Filter by status | Unit | `tests/unit/test_repos.py::test_query_by_status` |
| Filter by domain/type | Unit | `tests/unit/test_repos.py::test_query_by_domain_type` |
| Filter by date | Unit | `tests/unit/test_repos.py::test_query_by_date` |
| Combined filters | Unit | `tests/unit/test_repos.py::test_query_combined` |
| Pagination | Unit | `tests/unit/test_repos.py::test_query_pagination` |
| Get single | Unit | `tests/unit/test_repos.py::test_get_command` |

## Story Size

M (2000-5000 tokens, module implementation)

## Priority (MoSCoW)

Should Have

## Dependencies

- Commands must exist in metadata table

## Technical Notes

- Build query dynamically based on provided filters
- Use parameterized queries (no SQL injection)
- Index usage: (status, command_type), (domain, command_id), (updated_at)
- Default order: created_at DESC

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/api.py` - query_commands(), get_command()
- `src/commandbus/repositories/postgres.py` - Query building

**Constraints:**
- All filters are optional
- Must use parameterized queries
- Limit has reasonable default (100)
- Return CommandMetadata objects

**Verification Steps:**
1. Run `pytest tests/unit/test_repos.py::test_query -v`
2. Verify EXPLAIN ANALYZE shows index usage

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Acceptance criteria verified
- [ ] Documentation updated (if applicable)
- [ ] No regressions in related functionality
