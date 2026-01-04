# S049: Update Python Code for Schema-Qualified Names

## Parent Feature

[F010 - Database Schema Management](../F010-database-schema-management.md)

## User Story

**As a** developer
**I want** Python repository classes to use schema-qualified table names
**So that** the code works correctly with the new `commandbus` schema

## Context

After migrating tables to the `commandbus` schema, all SQL queries in the Python code need to reference tables using schema-qualified names (e.g., `commandbus.command` instead of `command_bus_command`). This story updates all repository classes and stored procedure calls.

## Acceptance Criteria (Given-When-Then)

### Scenario: Command repository uses schema-qualified names

**Given** the commandbus schema exists with all tables
**When** I call `command_repo.get(domain, command_id)`
**Then** the query references `commandbus.command` table
**And** the command metadata is returned correctly

### Scenario: Batch repository uses schema-qualified names

**Given** the commandbus schema exists
**When** I call `batch_repo.create(domain, batch_id, ...)`
**Then** the query references `commandbus.batch` table
**And** the batch is created correctly

### Scenario: Stored procedure calls use schema-qualified names

**Given** the commandbus schema exists with stored procedures
**When** I call `command_repo.sp_finish_command(...)`
**Then** it calls `commandbus.sp_finish_command`
**And** the command is updated correctly

### Scenario: Audit repository uses schema-qualified names

**Given** the commandbus schema exists
**When** I call `audit_logger.log(...)`
**Then** the query references `commandbus.audit` table
**And** the audit event is recorded

### Scenario: Troubleshooting queue uses schema-qualified names

**Given** the commandbus schema exists
**When** I call `tsq.list_troubleshooting(domain)`
**Then** queries reference `commandbus.command` and PGMQ archive tables
**And** results are returned correctly

### Scenario: All existing tests pass

**Given** all repository classes are updated
**When** I run `make test-integration`
**Then** all integration tests pass

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Command operations | Integration | `tests/integration/test_worker.py` |
| Batch operations | Integration | `tests/integration/test_batch.py` |
| TSQ operations | Integration | `tests/integration/test_troubleshooting_queue.py` |
| Query operations | Integration | `tests/integration/test_query.py` |

## Story Size

M (2000-4000 tokens, many files to update but mechanical changes)

## Priority (MoSCoW)

Must Have

## Dependencies

- S046 (V001 commandbus schema) completed
- S048 (Docker Flyway integration) completed

## Technical Notes

### Approach: Schema-Qualified Names

Update all table references to use explicit schema:
- `command_bus_command` -> `commandbus.command`
- `command_bus_batch` -> `commandbus.batch`
- `command_bus_audit` -> `commandbus.audit`
- `command_bus_payload_archive` -> `commandbus.payload_archive`

Update all stored procedure calls:
- `sp_receive_command` -> `commandbus.sp_receive_command`
- `sp_finish_command` -> `commandbus.sp_finish_command`
- etc.

### Alternative: search_path

Could set `search_path = commandbus, pgmq, public` on connections instead. This is less explicit but requires fewer code changes.

**Decision:** Use schema-qualified names for explicitness and clarity.

### Files to Modify

1. `src/commandbus/repositories/command.py`
   - Update all table references
   - Update stored procedure calls

2. `src/commandbus/repositories/batch.py`
   - Update all table references
   - Update stored procedure calls

3. `src/commandbus/repositories/audit.py`
   - Update table reference

4. `src/commandbus/ops/troubleshooting.py`
   - Update table references

5. `src/commandbus/ops/query.py`
   - Update table references

### Constants Approach

Consider defining table names as constants:

```python
# src/commandbus/constants.py
SCHEMA = "commandbus"
TABLE_COMMAND = f"{SCHEMA}.command"
TABLE_BATCH = f"{SCHEMA}.batch"
TABLE_AUDIT = f"{SCHEMA}.audit"
SP_RECEIVE_COMMAND = f"{SCHEMA}.sp_receive_command"
# etc.
```

## Verification Steps

1. Update all repository files
2. Run `make typecheck` - should pass
3. Run `make lint` - should pass
4. Run `make docker-up` - apply migrations
5. Run `make test-integration` - all tests should pass
6. Run `make test` - all unit tests should pass

## Definition of Done

- [ ] All repository classes updated with schema-qualified names
- [ ] All stored procedure calls updated
- [ ] Constants file created (optional but recommended)
- [ ] Type checking passes
- [ ] Linting passes
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] No regressions
