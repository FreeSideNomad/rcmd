# S070: Runtime Configuration Persistence & API

## Parent Feature

[F014 - Synchronous Wrappers & Runtime Toggle](../F014-sync-wrapper.md)

## User Story

**As an** operator configuring the E2E demo
**I want** the runtime mode (`async` or `sync`) stored alongside worker/retry settings
**So that** the UI and automation can reliably read/update the preference without touching code.

## Context

The `/api/v1/config` endpoint currently returns worker + retry structs stored in `e2e.config`. Introducing a runtime toggle requires schema changes, new Pydantic models, and persistence logic. Without this story, the settings UI (S071) and runtime manager (S072) have nothing to read.

## Acceptance Criteria

### Scenario: Config API returns runtime status
**Given** the config table contains a `runtime` JSON blob
**When** I call `GET /api/v1/config`
**Then** the response includes `runtime.mode` (`"async"` or `"sync"`) and optional `thread_pool_size`.

### Scenario: Runtime updates persist to database
**Given** I submit `PUT /api/v1/config` with a runtime payload
**When** the request succeeds
**Then** `e2e.config` upserts the `runtime` row
**And** subsequent GET requests reflect the new values.

### Scenario: Backward compatibility
**Given** the table lacks a `runtime` row (fresh install)
**When** I fetch the config
**Then** defaults (`mode="async"`, `thread_pool_size=null`) are returned
**And** saving other sections (worker/retry) continues to work.

## Technical Notes

- Update `tests/e2e/app/api/schemas.py`:
  - Add `RuntimeMode = Literal["async", "sync"]` and `RuntimeConfigSchema`.
  - Include runtime field on `ConfigResponse`, `ConfigUpdateRequest`, and `ConfigUpdateResponse`.
- Modify config endpoints in `tests/e2e/app/api/routes.py:538-587`:
  - `get_config`: select `"runtime"` row, fall back to defaults when absent.
  - `update_config`: insert/update runtime JSON when payload includes it.
- Extend `tests/e2e/app/config.py`:
  - `RuntimeConfig` dataclass with `.to_dict()` / `.from_dict()`.
  - `ConfigStore` loads/saves runtime along with worker/retry and exposes `.runtime` property.
- Ensure migrations not needed because `e2e.config` already stores arbitrary JSON.

## Test Coverage

| Criterion | Test Type | Location |
|-----------|-----------|----------|
| Schema serialization | Unit | `tests/unit/test_config_schemas.py` (new/updated) |
| API GET returns runtime defaults | Integration | `tests/e2e/tests/test_api.py::test_get_config_runtime_defaults` |
| API PUT persists runtime | Integration | `tests/e2e/tests/test_api.py::test_update_config_runtime` |
| ConfigStore round-trips runtime | Unit | `tests/unit/test_config_store.py` |

## Definition of Done

- [ ] Schemas + routes updated, runtime persisted.
- [ ] ConfigStore exposes runtime getters/setters.
- [ ] Tests covering defaults, persistence, error handling.
- [ ] Existing config functionality (worker/retry) remains untouched.
