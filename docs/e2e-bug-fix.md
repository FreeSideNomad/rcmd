# E2E Demo Application - Bug Fix Plan

## Overview

During manual testing of the E2E Demo Application, critical issues were discovered that prevent the application from functioning as a real demonstration of the commandbus library. The UI displays mock/random data instead of actual database data.

---

## Bug Summary

| Bug ID | Title | Severity | Component |
|--------|-------|----------|-----------|
| BUG-001 | E2E database not configured in Docker Compose | High | Infrastructure |
| BUG-002 | API endpoints return mock data instead of database data | Critical | Backend API |

---

## BUG-001: E2E Database Not Configured in Docker Compose

### Description
The E2E Demo Application expects to connect to a database named `commandbus_e2e` (configured in `tests/e2e/app/config.py`), but the `docker-compose.yml` only creates the `commandbus` database. Users cannot run the E2E demo without manual database setup.

### Current State
- `docker-compose.yml` creates only `commandbus` database
- `tests/e2e/app/config.py` defaults to `commandbus_e2e`
- `tests/e2e/.env` has a typo: `isbpostgresql://` instead of `postgresql://`
- No documentation on how to set up the E2E database
- No PGMQ queues created for the `e2e` domain

### Impact
- Users cannot run the E2E demo out of the box
- Manual database creation steps required
- Confusion between integration test database and E2E demo database

### Proposed Fix

#### Option A: Extend Docker Compose (Recommended)
Add initialization for `commandbus_e2e` database in `scripts/init-db.sql`:

```sql
-- Create E2E demo database
\connect postgres
CREATE DATABASE commandbus_e2e;
\connect commandbus_e2e

-- Enable PGMQ extension
CREATE EXTENSION IF NOT EXISTS pgmq;

-- Create command bus tables (same as main DB)
CREATE TABLE IF NOT EXISTS command_bus_command (...);
CREATE TABLE IF NOT EXISTS command_bus_audit (...);

-- Create e2e domain queues
SELECT pgmq.create('e2e__commands');
SELECT pgmq.create('e2e__replies');

-- Create e2e_config table for settings persistence
CREATE TABLE IF NOT EXISTS e2e_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### Option B: Use Same Database with Different Domain
Configure E2E to use `commandbus` database with `e2e` domain to isolate data.

### Files to Modify
- `scripts/init-db.sql` - Add E2E database setup
- `tests/e2e/.env` - Fix typo in DATABASE_URL
- `tests/e2e/.env.example` - Ensure correct example URL
- `Makefile` - Add `make e2e-setup` target
- `README.md` or `tests/e2e/README.md` - Add setup instructions

### Acceptance Criteria
- [ ] `make docker-up` creates both `commandbus` and `commandbus_e2e` databases
- [ ] E2E demo starts without additional manual setup
- [ ] PGMQ queues for `e2e` domain exist
- [ ] `.env` file has correct database URL

---

## BUG-002: API Endpoints Return Mock Data Instead of Database Data

### Description
All API endpoints in `tests/e2e/app/api/routes.py` return randomly generated mock data instead of querying the actual database. The UI appears to work but shows fake statistics that change on every refresh.

### Current State

The following endpoints return mock/random data:

| Endpoint | Current Behavior | Should Query |
|----------|------------------|--------------|
| `GET /api/v1/stats/overview` | Returns `random.randint()` values | `command_bus_command` table counts by status |
| `GET /api/v1/stats/recent-activity` | Returns mock events | `command_bus_audit` table recent entries |
| `GET /api/v1/stats/throughput` | Returns random metrics | Calculate from audit timestamps |
| `GET /api/v1/stats/load-test` | Returns random progress | Track actual load test state |
| `GET /api/v1/commands` | Calls `_generate_mock_commands()` | `command_bus_command` with filters |
| `GET /api/v1/commands/<id>` | Returns hardcoded data | `command_bus_command` by ID |
| `POST /api/v1/commands` | Returns fake ID, no persistence | Insert via `CommandBus.send()` |
| `POST /api/v1/commands/bulk` | Returns fake IDs, no persistence | Bulk insert via `CommandBus` |
| `GET /api/v1/tsq` | Calls `_generate_mock_tsq_commands()` | `TroubleshootingQueue.list_commands()` |
| `POST /api/v1/tsq/<id>/retry` | Returns success, no action | `TroubleshootingQueue.operator_retry()` |
| `POST /api/v1/tsq/<id>/cancel` | Returns success, no action | `TroubleshootingQueue.operator_cancel()` |
| `POST /api/v1/tsq/<id>/complete` | Returns success, no action | `TroubleshootingQueue.operator_complete()` |
| `POST /api/v1/tsq/bulk-retry` | Returns success, no action | Bulk `operator_retry()` |
| `GET /api/v1/audit/<id>` | Calls `_generate_mock_audit_events()` | `command_bus_audit` by command_id |
| `GET /api/v1/audit/search` | Calls `_generate_mock_search_events()` | `command_bus_audit` with filters |
| `GET /api/v1/config` | Returns hardcoded defaults | `e2e_config` table |
| `PUT /api/v1/config` | Returns success, no persistence | Update `e2e_config` table |

### Impact
- Dashboard shows fake statistics that don't reflect real data
- Commands are not actually created or processed
- TSQ operations don't actually modify command state
- Audit trail shows fake events
- Settings changes are not persisted
- The demo is essentially non-functional for actual testing

### Proposed Fix

#### Architecture Changes

1. **Add Database Pool to Flask App Context**
   - Initialize `AsyncConnectionPool` in `create_app()`
   - Store pool in `app.config['pool']`
   - Create helper to get pool in route handlers

2. **Use Async Route Handlers**
   - Install `asgiref` or use Flask's async support (Flask 2.0+)
   - Convert route handlers to async functions
   - Use `asyncio.run()` wrapper or async Flask

3. **Integrate CommandBus and TroubleshootingQueue**
   - Import from `commandbus` package
   - Create instances in route handlers
   - Use proper domain (`e2e`)

#### Endpoint Implementation Priority

**Phase 1 - Core Functionality (P1)**
1. `POST /api/v1/commands` - Create real commands via CommandBus
2. `GET /api/v1/commands` - Query command_bus_command table
3. `GET /api/v1/commands/<id>` - Get single command
4. `GET /api/v1/stats/overview` - Real status counts
5. `GET /api/v1/tsq` - Real TSQ listing
6. `POST /api/v1/tsq/<id>/retry` - Real retry operation
7. `POST /api/v1/tsq/<id>/cancel` - Real cancel operation
8. `POST /api/v1/tsq/<id>/complete` - Real complete operation

**Phase 2 - Audit & Stats (P2)**
1. `GET /api/v1/audit/<id>` - Real audit events
2. `GET /api/v1/audit/search` - Real audit search
3. `GET /api/v1/stats/recent-activity` - Real recent events
4. `GET /api/v1/config` - Load from e2e_config table
5. `PUT /api/v1/config` - Save to e2e_config table

**Phase 3 - Load Testing (P3)**
1. `POST /api/v1/commands/bulk` - Real bulk creation
2. `GET /api/v1/stats/throughput` - Real metrics
3. `GET /api/v1/stats/load-test` - Real progress tracking
4. `POST /api/v1/tsq/bulk-retry` - Real bulk retry

### Files to Modify
- `tests/e2e/app/__init__.py` - Add database pool initialization
- `tests/e2e/app/api/routes.py` - Replace all mock functions with real DB queries
- `tests/e2e/app/config.py` - Ensure correct DB URL handling

### Acceptance Criteria
- [ ] All endpoints query actual database
- [ ] Commands created via UI appear in database
- [ ] Dashboard stats reflect real data
- [ ] TSQ operations modify command state
- [ ] Audit trail shows real events
- [ ] Settings persist across restarts
- [ ] No random/mock data generators remain

---

## Implementation Order

1. **BUG-001 first** - Database must exist before API can connect
2. **BUG-002 Phase 1** - Core command and TSQ functionality
3. **BUG-002 Phase 2** - Audit and configuration
4. **BUG-002 Phase 3** - Load testing features

---

## Testing Verification

After fixes, verify:

1. Start fresh: `make docker-down && make docker-up`
2. Start E2E app: `cd tests/e2e && python run.py`
3. Dashboard shows zeros (empty database)
4. Send a command via UI
5. Command appears in database: `SELECT * FROM command_bus_command`
6. Dashboard updates with real counts
7. Start a worker, command processes
8. Audit trail shows real events
9. TSQ operations work with permanent failure commands

---

## GitHub Issues to Create

### Issue 1: E2E Database Setup Not Configured

**Title:** E2E Demo: Database `commandbus_e2e` not created by Docker Compose

**Labels:** `bug`, `e2e`, `infrastructure`

**Body:**
```markdown
## Description
The E2E Demo Application expects to connect to `commandbus_e2e` database, but Docker Compose only creates `commandbus`. Users cannot run the demo without manual setup.

## Current Behavior
- `docker-compose.yml` only creates `commandbus` database
- E2E app config defaults to `commandbus_e2e`
- `.env` file has typo: `isbpostgresql://` instead of `postgresql://`
- No setup documentation

## Expected Behavior
- `make docker-up` should create both databases
- E2E demo should work out of the box
- Clear documentation for setup

## Files Affected
- `scripts/init-db.sql`
- `tests/e2e/.env`
- `tests/e2e/.env.example`
- `Makefile`

## Acceptance Criteria
- [ ] `make docker-up` creates `commandbus_e2e` database
- [ ] PGMQ extension enabled in E2E database
- [ ] `e2e__commands` queue created
- [ ] `.env` typo fixed
- [ ] Setup documented
```

### Issue 2: E2E API Returns Mock Data Instead of Database Data

**Title:** E2E Demo: All API endpoints return mock/random data instead of real database queries

**Labels:** `bug`, `e2e`, `critical`

**Body:**
```markdown
## Description
All API endpoints in `tests/e2e/app/api/routes.py` return randomly generated mock data. The UI appears functional but shows fake statistics that change on every refresh.

## Current Behavior
- Dashboard shows random numbers (e.g., `random.randint(10000, 15000)` for completed count)
- Commands are not persisted to database
- TSQ operations don't modify state
- Audit trail shows fake events

## Expected Behavior
- All endpoints should query actual database tables
- Commands created via UI should persist
- Dashboard stats should reflect real data
- TSQ operations should work

## Affected Endpoints
| Endpoint | Issue |
|----------|-------|
| GET /stats/overview | Returns random counts |
| GET /stats/recent-activity | Mock events |
| GET /commands | Mock command list |
| POST /commands | No persistence |
| GET /tsq | Mock TSQ list |
| POST /tsq/*/retry,cancel,complete | No action |
| GET /audit/* | Mock audit events |
| GET/PUT /config | No persistence |

## Files Affected
- `tests/e2e/app/__init__.py`
- `tests/e2e/app/api/routes.py`

## Acceptance Criteria
- [ ] Database pool initialized in Flask app
- [ ] All endpoints query real database
- [ ] No `random.randint()` or mock generators
- [ ] Commands persist to `command_bus_command`
- [ ] TSQ operations use `TroubleshootingQueue` class
- [ ] Audit queries `command_bus_audit` table
```

---

## Notes

- The mock data implementation was likely intended as a temporary placeholder during UI development
- Comments in code like `"database persistence coming in future iteration"` confirm this
- The test plan in `docs/e2e-test-plan.md` assumes real database connectivity and will fail without these fixes
