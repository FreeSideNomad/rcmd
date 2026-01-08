# S072: Runtime-Aware FastAPI Dependency Manager

## Parent Feature

[F014 - Synchronous Wrappers & Runtime Toggle](../F014-sync-wrapper.md)

## User Story

**As a** developer running the E2E FastAPI app
**I want** dependencies (CommandBus, TroubleshootingQueue, Process Manager, etc.) to honor the configured runtime
**So that** the API keeps its async signatures while executing using either async or sync implementations under the hood.

## Context

Even with sync facades and persisted runtime config, FastAPI endpoints currently call the async classes directly (e.g., `await bus.send`). Switching to sync mode must not force `@router` methods to change signatures. Instead, a runtime manager should dispatch to the appropriate backend (async or sync) and manage lifecycle (startup/shutdown). This manager also centralizes access for other app components (Process Manager, dependencies).

## Acceptance Criteria

### Scenario: Runtime manager selects implementations
**Given** runtime config is set to `"sync"`
**When** a FastAPI handler resolves `Bus` dependency and invokes `await bus.send(...)`
**Then** the call executes via `SyncCommandBus` (through `asyncio.to_thread` or similar)
**And** results/errors match the async code path.

### Scenario: Switching back to async
**Given** runtime config flips to `"async"` and the app restarts
**When** handlers run
**Then** they use native async implementations without thread hops.

### Scenario: Graceful shutdown
**Given** the ASGI app stops
**When** the lifespan context exits
**Then** the runtime manager shuts down `SyncRuntime` threads/executors so no resources leak.

## Technical Notes

- Add `tests/e2e/app/runtime.py` implementing a `RuntimeManager`:
  - Initialize shared resources in `startup()` (pool already available via `main.py`).
  - Keep references to `CommandBus`, `TroubleshootingQueue`, `ProcessReplyRouter`, and their sync counterparts.
  - Provide async wrappers (e.g., `async def send_command(...)`) delegating to sync via `asyncio.to_thread` when `mode == "sync"`.
  - Expose `get_bus()`, `get_tsq()`, `get_process_repo()`, `get_report_process()`, plus `reload_config()` helper.
  - Manage `SyncRuntime` lifecycle; share runtime among all sync wrappers.
- Update `tests/e2e/app/main.py`:
  - During startup: instantiate `ConfigStore`, runtime manager, and store on `app.state`.
  - On shutdown: call manager.shutdown().
- Revise `tests/e2e/app/dependencies.py`:
  - Fetch dependencies from `request.app.state.runtime_manager` rather than constructing new objects each request.
  - Keep type aliases stable (Bus, TSQ, etc.).
- Ensure `StatementReportProcess` and process repository continue to function when commands are dispatched via the manager.
- Document usage/architecture in `docs/features/F014-sync-wrapper.md`.

## Test Coverage

| Criterion | Test Type | Location |
|-----------|-----------|----------|
| RuntimeManager async path | Unit | `tests/unit/test_runtime_manager.py::test_async_mode` |
| RuntimeManager sync path via to_thread | Unit | `tests/unit/test_runtime_manager.py::test_sync_mode` |
| FastAPI dependency wiring | Integration | `tests/e2e/tests/test_api.py::test_commands_respect_runtime` |
| Shutdown releases resources | Unit | `tests/unit/test_runtime_manager.py::test_shutdown_stops_runtime` |

## Definition of Done

- [ ] RuntimeManager module created, integrated into FastAPI app.
- [ ] Dependencies resolved via manager for bus/tsq/process components.
- [ ] Mode switches honored after restart; manual smoke instructions documented.
- [ ] Tests cover both runtime branches and shutdown.
