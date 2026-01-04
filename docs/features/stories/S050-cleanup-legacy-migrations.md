# S050: Clean Up Legacy Migrations and E2E Test Infrastructure

## Parent Feature

[F010 - Database Schema Management](../F010-database-schema-management.md)

## User Story

**As a** maintainer
**I want** to remove outdated migration files and update E2E test infrastructure
**So that** there is a single, consistent migration path for all environments

## Context

The `tests/e2e/migrations/` directory contains outdated Flyway migrations (V001-V004) that are missing batch support and stored procedures. This story cleans up these legacy files, updates the E2E test infrastructure to use the new centralized migrations, and ensures all test environments use the same schema.

## Acceptance Criteria (Given-When-Then)

### Scenario: Remove legacy e2e migrations

**Given** `tests/e2e/migrations/` contains V001-V004 files
**When** I complete this story
**Then** the legacy migration files are removed
**And** E2E tests use the centralized `migrations/` directory

### Scenario: E2E tests use new schema

**Given** the centralized migrations are applied
**When** E2E tests run
**Then** they reference `commandbus.command` (not `command_bus_command`)
**And** they reference `e2e.test_command` (not `test_command`)
**And** all tests pass

### Scenario: E2E app code updated

**Given** the E2E app uses test_command table
**When** I update the E2E app code
**Then** it references `e2e.test_command`
**And** it references `e2e.config`
**And** the E2E app works correctly

### Scenario: Flyway configuration updated

**Given** tests/e2e uses Flyway
**When** Flyway runs
**Then** it uses the centralized `migrations/` directory
**And** migrations are applied correctly

### Scenario: Integration tests work with new schema

**Given** integration tests exist
**When** I run `make test-integration`
**Then** all tests pass with the new schema
**And** no references to old table names remain

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| E2E tests pass | E2E | `tests/e2e/` |
| Integration tests pass | Integration | `tests/integration/` |
| Schema references correct | Manual | Code review |

## Story Size

M (2000-4000 tokens, cleanup and updates across multiple files)

## Priority (MoSCoW)

Must Have

## Dependencies

- S046 (V001 commandbus schema) completed
- S047 (V002 e2e schema) completed
- S048 (Docker Flyway integration) completed
- S049 (Python schema-qualified names) completed

## Technical Notes

### Files to Remove

```
tests/e2e/migrations/
├── V001__pgmq_extension.sql      # Remove (PGMQ in V001)
├── V002__commandbus_schema.sql   # Remove (outdated, replaced by V001)
├── V003__pgmq_queues.sql         # Remove (handled elsewhere)
└── V004__test_command_table.sql  # Remove (replaced by V002 e2e schema)
```

### Files to Update

1. **`tests/e2e/flyway.conf`** (or equivalent)
   - Point to centralized `migrations/` directory

2. **`tests/e2e/app/` Python files**
   - Update table references to `e2e.test_command`, `e2e.config`

3. **`tests/e2e/docker-compose.yml`** (if exists)
   - Update Flyway configuration

4. **Integration test fixtures**
   - Ensure they work with new schema names

### Search Path Alternative

If E2E app sets `search_path = commandbus, e2e, pgmq, public`, fewer code changes needed. Consider this approach for E2E code.

## Verification Steps

1. Remove legacy migration files
2. Update E2E Flyway configuration
3. Update E2E app code for new table names
4. Run `make docker-up` - verify migrations apply
5. Run `make test-integration` - all should pass
6. Run E2E tests - all should pass
7. Verify no references to old table names remain:
   ```bash
   grep -r "command_bus_command" tests/
   grep -r "command_bus_batch" tests/
   ```

## Definition of Done

- [ ] Legacy `tests/e2e/migrations/` files removed
- [ ] E2E Flyway config points to centralized migrations
- [ ] E2E app code updated for new schema names
- [ ] Integration tests pass
- [ ] E2E tests pass
- [ ] No references to old table names in codebase
- [ ] Documentation updated
