# S046: Consolidate Command Bus Schema (V1 Migration)

## Parent Feature

[F010 - Database Schema Management](../F010-database-schema-management.md)

## User Story

**As a** platform engineer
**I want** all command bus database objects consolidated into a dedicated `commandbus` schema
**So that** the database is properly organized and migrations are the single source of truth

## Context

Currently, command bus tables exist in the public schema and are defined in two places: `scripts/init-db.sql` (complete) and `tests/e2e/migrations/` (outdated). This story consolidates everything into a single V1 migration file that creates the `commandbus` schema with all current tables and stored procedures.

## Acceptance Criteria (Given-When-Then)

### Scenario: Create commandbus schema with all tables

**Given** a fresh PostgreSQL database with PGMQ extension
**When** the V001 migration runs
**Then** the `commandbus` schema is created
**And** the following tables exist in `commandbus` schema:
  - `commandbus.command` (command metadata)
  - `commandbus.batch` (batch tracking)
  - `commandbus.audit` (audit events)
  - `commandbus.payload_archive` (archived payloads)
**And** all required indexes are created
**And** foreign key from `command.batch_id` to `batch` exists

### Scenario: Create all stored procedures

**Given** the commandbus schema exists
**When** the V001 migration completes
**Then** the following stored procedures exist:
  - `commandbus.sp_receive_command`
  - `commandbus.sp_finish_command`
  - `commandbus.sp_start_batch`
  - `commandbus.sp_update_batch_counters`
  - `commandbus.sp_tsq_complete`
  - `commandbus.sp_tsq_cancel`
  - `commandbus.sp_tsq_retry`

### Scenario: Migration is idempotent

**Given** the V001 migration has already run
**When** Flyway is run again
**Then** the migration is skipped (already applied)
**And** no errors occur

### Scenario: Tables have correct structure

**Given** the V001 migration has run
**When** I describe the `commandbus.command` table
**Then** it has columns:
  - domain (TEXT NOT NULL)
  - queue_name (TEXT NOT NULL)
  - msg_id (BIGINT NULL)
  - command_id (UUID NOT NULL)
  - command_type (TEXT NOT NULL)
  - status (TEXT NOT NULL)
  - attempts (INT NOT NULL DEFAULT 0)
  - max_attempts (INT NOT NULL)
  - lease_expires_at (TIMESTAMPTZ NULL)
  - last_error_type (TEXT NULL)
  - last_error_code (TEXT NULL)
  - last_error_msg (TEXT NULL)
  - created_at (TIMESTAMPTZ NOT NULL DEFAULT NOW())
  - updated_at (TIMESTAMPTZ NOT NULL DEFAULT NOW())
  - reply_queue (TEXT NOT NULL DEFAULT '')
  - correlation_id (UUID NULL)
  - batch_id (UUID NULL)

### Scenario: Batch table has correct structure

**Given** the V001 migration has run
**When** I describe the `commandbus.batch` table
**Then** it has columns:
  - domain (TEXT NOT NULL)
  - batch_id (UUID NOT NULL)
  - name (TEXT NULL)
  - custom_data (JSONB NULL)
  - status (TEXT NOT NULL DEFAULT 'PENDING')
  - total_count (INT NOT NULL DEFAULT 0)
  - completed_count (INT NOT NULL DEFAULT 0)
  - canceled_count (INT NOT NULL DEFAULT 0)
  - in_troubleshooting_count (INT NOT NULL DEFAULT 0)
  - created_at (TIMESTAMPTZ NOT NULL DEFAULT NOW())
  - started_at (TIMESTAMPTZ NULL)
  - completed_at (TIMESTAMPTZ NULL)
**And** primary key is (domain, batch_id)

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Schema created | Integration | `tests/integration/test_migrations.py::test_v001_creates_schema` |
| Tables exist | Integration | `tests/integration/test_migrations.py::test_v001_creates_tables` |
| SPs exist | Integration | `tests/integration/test_migrations.py::test_v001_creates_stored_procedures` |
| Idempotent | Integration | `tests/integration/test_migrations.py::test_migrations_idempotent` |

## Story Size

L (4000-8000 tokens, large feature - many SQL objects to create)

## Priority (MoSCoW)

Must Have

## Dependencies

- PostgreSQL with PGMQ extension
- Flyway migration tool configured

## Technical Notes

- Use `CREATE SCHEMA IF NOT EXISTS commandbus;`
- Set `search_path` at start of migration for convenience
- Copy all current content from `scripts/init-db.sql`
- Rename tables: `command_bus_X` -> `commandbus.X`
- Ensure stored procedures use schema-qualified table names
- PGMQ tables remain in `pgmq` schema (managed by extension)

## Files to Create/Modify

**Create:**
- `migrations/V001__commandbus_schema.sql` - Full schema migration

**Reference (copy from):**
- `scripts/init-db.sql` - Current table definitions and stored procedures

## Verification Steps

1. Run `docker compose down -v` to clear existing data
2. Run Flyway migration
3. Verify schema: `\dn` should show `commandbus`
4. Verify tables: `\dt commandbus.*` should list all tables
5. Verify functions: `\df commandbus.*` should list all stored procedures

## Definition of Done

- [ ] V001 migration file created
- [ ] All tables created in commandbus schema
- [ ] All stored procedures created in commandbus schema
- [ ] All indexes created
- [ ] Migration tested on fresh database
- [ ] Migration tested on existing database (idempotent)
