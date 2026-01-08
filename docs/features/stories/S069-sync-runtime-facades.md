# S069: Synchronous Runtime & Facades

## Parent Feature

[F014 - Synchronous Wrappers & Runtime Toggle](../F014-sync-wrapper.md)

## User Story

**As a** Python engineer integrating Command Bus into a synchronous app (Flask/Django/CLI)
**I want** official blocking wrappers for the core async APIs
**So that** I can reuse existing handlers, repositories, and retry logic without writing custom event loop plumbing.

## Context

The library is async-first (`CommandBus`, `Worker`, `TroubleshootingQueue`, `ProcessReplyRouter`). Users running synchronous frameworks currently have to call `asyncio.run()` or cobble together their own thread pools, which is error-prone and inconsistent. ADR `docs/ADR-sync-wrapper.md` and the design doc `docs/syncronous-python-design.md` outline a thread-backed runtime that should be codified directly inside the package.

Delivering a `commandbus.sync` package gives downstream features (including the E2E runtime toggle) a stable foundation. All subsequent stories in F014 rely on this one.

## Acceptance Criteria (Given-When-Then)

### Scenario: Blocking send via SyncCommandBus
**Given** I instantiate `SyncCommandBus` with an async `CommandBus`
**When** I call `bus.send(...)` without `await`
**Then** the call blocks until the async operation completes
**And** any raised `CommandBusError` surfaces unchanged.

### Scenario: Worker lifecycle under SyncWorker
**Given** I wrap an existing `Worker` inside `SyncWorker`
**When** I call `run()` with optional thread pool size overrides
**Then** a background loop starts on a managed event loop thread
**And** calling `stop()` joins the worker thread and shuts down executors without leaks.

### Scenario: TroubleshootingQueue and Process Router parity
**Given** I wrap `TroubleshootingQueue` or `ProcessReplyRouter` via the sync package
**When** I call any blocking method (e.g., `list_all_troubleshooting`, `run`)
**Then** the underlying async implementation executes via the shared runtime
**And** results/exceptions match the async behavior.

## Technical Notes

- Add `src/commandbus/sync/` with:
  - `runtime.py`: `SyncRuntime` maintaining a background `asyncio` loop thread with `run`, `run_many`, `shutdown`, context manager, and `atexit` hook.
  - `config.py`: helper `configure(runtime=None, thread_pool_size=None)` plus env var fallback `COMMAND_BUS_SYNC_THREADS`.
  - `bus.py`, `worker.py`, `tsq.py`, `process.py`: thin blocking facades delegating to async implementations via `SyncRuntime`.
  - `__init__.py`: export `SyncRuntime`, `SyncCommandBus`, `SyncWorker`, `SyncTroubleshootingQueue`, `SyncProcessReplyRouter`, `configure`.
- Update `src/commandbus/__init__.py` to re-export sync symbols so library consumers get one import path.
- Provide doc samples in `README.md` and `docs/python-library-best-practices.md` for usage.
- Ensure constructors accept either fully built async instances or init kwargs (e.g., `pool`, `domain`) for ergonomics.

## Test Coverage

| Criterion | Test Type | Location |
|-----------|-----------|----------|
| SyncRuntime run/shutdown/exception handling | Unit | `tests/unit/test_sync_runtime.py` |
| SyncCommandBus delegates methods | Unit | `tests/unit/test_sync_bus.py` |
| SyncWorker lifecycle & thread pool size | Unit | `tests/unit/test_sync_worker.py` |
| SyncTroubleshootingQueue & ProcessRouter parity | Unit | `tests/unit/test_sync_tsq.py`, `test_sync_process_router.py` |
| Smoke test for blocking send | Integration | `tests/integration/test_sync_mode.py::test_sync_bus_send` |

## Definition of Done

- [ ] New `commandbus.sync` package implemented with runtime + facades.
- [ ] Sync symbols exported through `commandbus.__all__`.
- [ ] Unit tests cover runtime + wrappers; integration smoke passes.
- [ ] Documentation updated with synchronous usage guidance.
- [ ] No regressions in existing async tests (`make test` clean).
