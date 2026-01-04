# F010: Database Schema Management

## Problem Statement

The current database schema management has several issues:

1. **Dual sources of truth**: `scripts/init-db.sql` and `tests/e2e/migrations/` contain different schema definitions
2. **Out of sync**: E2E migrations are missing:
   - `command_bus_batch` table
   - `batch_id` column on `command_bus_command`
   - All stored procedures (`sp_receive_command`, `sp_finish_command`, `sp_update_batch_counters`, etc.)
3. **No schema separation**: Command bus tables and e2e test tables are mixed in the public schema
4. **No migration strategy**: Development uses `init-db.sql` which recreates everything, but production needs versioned migrations

## Goals

1. Establish migrations as the single source of truth for all database changes
2. Separate concerns using PostgreSQL schemas:
   - `commandbus` schema: Core command bus tables and stored procedures
   - `e2e` schema: Test-specific tables (`test_command`, `e2e_config`)
3. Consolidate all current command bus objects into V1 migration
4. Move e2e-specific objects to V2 migration
5. Docker development should use the same migration system

## Schema Design

### `commandbus` Schema (V1)

Tables:
- `commandbus.command` (renamed from `command_bus_command`)
- `commandbus.batch` (renamed from `command_bus_batch`)
- `commandbus.audit` (renamed from `command_bus_audit`)
- `commandbus.payload_archive` (renamed from `command_bus_payload_archive`)

Stored Procedures:
- `commandbus.sp_receive_command`
- `commandbus.sp_finish_command`
- `commandbus.sp_start_batch`
- `commandbus.sp_update_batch_counters`
- `commandbus.sp_tsq_complete`
- `commandbus.sp_tsq_cancel`
- `commandbus.sp_tsq_retry`

### `e2e` Schema (V2)

Tables:
- `e2e.test_command`
- `e2e.config`

## Migration Strategy

### Directory Structure
```
migrations/
├── V001__commandbus_schema.sql    # Core command bus (tables + SPs)
├── V002__e2e_schema.sql           # E2E test tables (optional)
└── ...
```

### Docker Development
- Replace `scripts/init-db.sql` with Flyway migrations
- `docker-compose.yml` runs Flyway on startup
- Same migrations used for dev, integration tests, and e2e tests

### Python Code Changes
- Update all SQL queries to use schema-qualified names (e.g., `commandbus.command`)
- Or set `search_path` on connection to include `commandbus` schema

## Stories

### S046: Consolidate Command Bus Schema (V1)
Create `V001__commandbus_schema.sql` containing:
- Create `commandbus` schema
- All command bus tables with proper naming
- All stored procedures
- All indexes

### S047: Create E2E Schema (V2)
Create `V002__e2e_schema.sql` containing:
- Create `e2e` schema
- `test_command` table
- `config` table with defaults

### S048: Update Docker Compose
- Add Flyway container or init script
- Remove `scripts/init-db.sql`
- Ensure migrations run on container startup

### S049: Update Python Code
- Update repository classes to use schema-qualified table names
- Update stored procedure calls
- Ensure backward compatibility during transition

### S050: Update Integration Tests
- Tests should use the same migration system
- Clean up between test runs without recreating schema

## Decision Points

1. **Table naming**: Keep `command_bus_` prefix or use schema + simple names?
   - Option A: `commandbus.command_bus_command` (redundant)
   - Option B: `commandbus.command` (cleaner, breaking change)

2. **PGMQ queues**: PGMQ creates tables in `pgmq` schema - no changes needed

3. **Search path vs qualified names**:
   - Option A: Set `search_path = commandbus, pgmq, public` on connections
   - Option B: Use fully qualified names everywhere

4. **Backward compatibility**: How to handle existing deployments?
   - This is a development project, so full migration is acceptable

## Acceptance Criteria

- [ ] Single source of truth for database schema (migrations only)
- [ ] `commandbus` schema contains all command bus objects
- [ ] `e2e` schema contains test-specific objects
- [ ] Docker development uses Flyway migrations
- [ ] Integration tests use same migration system
- [ ] E2E tests use same migration system
- [ ] `scripts/init-db.sql` removed or deprecated
- [ ] All Python code works with new schema structure
