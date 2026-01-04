# S047: Create E2E Test Schema (V2 Migration)

## Parent Feature

[F010 - Database Schema Management](../F010-database-schema-management.md)

## User Story

**As a** test engineer
**I want** E2E test tables isolated in a dedicated `e2e` schema
**So that** test infrastructure is clearly separated from production command bus tables

## Context

The E2E testing framework uses tables like `test_command` and `e2e_config` to control test behavior. These should not be in the public schema or mixed with command bus tables. This story creates a V2 migration that sets up the `e2e` schema with all test-specific tables.

## Acceptance Criteria (Given-When-Then)

### Scenario: Create e2e schema with test tables

**Given** the V001 migration (commandbus schema) has run
**When** the V002 migration runs
**Then** the `e2e` schema is created
**And** the following tables exist in `e2e` schema:
  - `e2e.test_command` (test behavior specifications)
  - `e2e.config` (worker/retry configuration)

### Scenario: Test command table structure

**Given** the V002 migration has run
**When** I describe the `e2e.test_command` table
**Then** it has columns:
  - id (SERIAL PRIMARY KEY)
  - command_id (UUID NOT NULL UNIQUE)
  - payload (JSONB NOT NULL DEFAULT '{}')
  - behavior (JSONB NOT NULL)
  - created_at (TIMESTAMPTZ DEFAULT NOW())
  - processed_at (TIMESTAMPTZ NULL)
  - attempts (INTEGER DEFAULT 0)
  - result (JSONB NULL)
**And** indexes exist on command_id and created_at

### Scenario: Config table with defaults

**Given** the V002 migration has run
**When** I query `e2e.config`
**Then** it contains default rows:
  - key='worker': visibility_timeout, concurrency, poll_interval, batch_size
  - key='retry': max_attempts, base_delay_ms, max_delay_ms, backoff_multiplier

### Scenario: E2E schema is optional

**Given** the V001 migration has run
**And** V002 migration is not applied
**When** the command bus application starts
**Then** it operates normally (e2e tables not required for production)

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Schema created | Integration | `tests/integration/test_migrations.py::test_v002_creates_e2e_schema` |
| Tables exist | Integration | `tests/integration/test_migrations.py::test_v002_creates_e2e_tables` |
| Default config | Integration | `tests/integration/test_migrations.py::test_v002_inserts_default_config` |

## Story Size

S (1000-2000 tokens, small feature)

## Priority (MoSCoW)

Should Have

## Dependencies

- S046 (V001 commandbus schema) completed
- Flyway migration tool configured

## Technical Notes

- Use `CREATE SCHEMA IF NOT EXISTS e2e;`
- Copy table definitions from existing `tests/e2e/migrations/V004__test_command_table.sql`
- Insert default config values
- This migration is optional for production deployments

## Files to Create/Modify

**Create:**
- `migrations/V002__e2e_schema.sql` - E2E test schema migration

**Reference (copy from):**
- `tests/e2e/migrations/V004__test_command_table.sql` - Current table definitions

## Verification Steps

1. Run V001 and V002 migrations
2. Verify schema: `\dn` should show both `commandbus` and `e2e`
3. Verify tables: `\dt e2e.*` should list test_command and config
4. Verify config: `SELECT * FROM e2e.config` should return 2 rows

## Definition of Done

- [ ] V002 migration file created
- [ ] e2e schema created
- [ ] test_command table with correct structure
- [ ] config table with default values
- [ ] Migration tested
