# S048: Update Docker Compose for Flyway Migrations

## Parent Feature

[F010 - Database Schema Management](../F010-database-schema-management.md)

## User Story

**As a** developer
**I want** Docker Compose to automatically run Flyway migrations on startup
**So that** my local development environment always has the correct schema

## Context

Currently, Docker Compose uses `scripts/init-db.sql` which runs only on fresh database creation. This story updates the Docker setup to use Flyway migrations, ensuring the same migration process is used across development, testing, and production environments.

## Acceptance Criteria (Given-When-Then)

### Scenario: Fresh database initialization

**Given** no Docker volumes exist
**When** I run `docker compose up -d`
**Then** PostgreSQL starts
**And** Flyway runs all migrations (V001, V002, ...)
**And** both `commandbus` and `e2e` schemas exist
**And** all tables and stored procedures are created

### Scenario: Existing database with new migration

**Given** Docker volumes exist with V001 applied
**And** a new V003 migration file is added
**When** I run `docker compose up -d`
**Then** Flyway runs only the new V003 migration
**And** existing data is preserved

### Scenario: Migration failure handling

**Given** a migration file has a syntax error
**When** I run `docker compose up -d`
**Then** Flyway reports the error
**And** the container exits with non-zero status
**And** the database is left in a consistent state

### Scenario: Clean rebuild

**Given** Docker volumes exist
**When** I run `docker compose down -v && docker compose up -d`
**Then** all volumes are removed
**And** Flyway runs all migrations from scratch
**And** the database is freshly initialized

### Scenario: Make targets still work

**Given** docker-compose.yml is updated
**When** I run `make docker-up`
**Then** the database starts with migrations applied
**When** I run `make test-integration`
**Then** integration tests pass against the migrated schema

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Fresh init | Manual | Run `docker compose down -v && docker compose up` |
| Schema exists | Manual | `docker compose exec postgres psql -c '\dn'` |
| Migrations recorded | Manual | `SELECT * FROM flyway_schema_history` |

## Story Size

M (2000-4000 tokens, medium complexity)

## Priority (MoSCoW)

Must Have

## Dependencies

- S046 (V001 commandbus schema) completed
- S047 (V002 e2e schema) completed

## Technical Notes

### Option A: Flyway Container (Recommended)
Add a Flyway service to docker-compose.yml:

```yaml
services:
  flyway:
    image: flyway/flyway:10
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./migrations:/flyway/sql
    command: migrate
    environment:
      FLYWAY_URL: jdbc:postgresql://postgres:5432/commandbus
      FLYWAY_USER: postgres
      FLYWAY_PASSWORD: postgres
```

### Option B: Init Script with Flyway
Use a custom entrypoint script that runs Flyway before starting PostgreSQL.

### Changes Required

1. Create `migrations/` directory at project root
2. Move/create V001 and V002 migration files
3. Update `docker-compose.yml` to add Flyway service
4. Remove or deprecate `scripts/init-db.sql`
5. Update Makefile if needed

## Files to Create/Modify

**Create:**
- `migrations/` directory structure

**Modify:**
- `docker-compose.yml` - Add Flyway service
- `Makefile` - Update docker-up target if needed

**Deprecate:**
- `scripts/init-db.sql` - Mark as deprecated or remove

## Verification Steps

1. Run `docker compose down -v` to clean up
2. Run `docker compose up -d`
3. Check Flyway output: `docker compose logs flyway`
4. Verify schemas: `docker compose exec postgres psql -U postgres -d commandbus -c '\dn'`
5. Verify tables: `docker compose exec postgres psql -U postgres -d commandbus -c '\dt commandbus.*'`
6. Run `make test-integration` to verify tests pass

## Definition of Done

- [ ] migrations/ directory created with V001, V002
- [ ] docker-compose.yml updated with Flyway service
- [ ] Fresh database init works via `docker compose up`
- [ ] Incremental migrations work
- [ ] Integration tests pass
- [ ] scripts/init-db.sql deprecated or removed
- [ ] Makefile targets still work
