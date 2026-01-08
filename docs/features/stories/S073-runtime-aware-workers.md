# S073: Runtime-Aware Worker & Router Orchestration

## Parent Feature

[F014 - Synchronous Wrappers & Runtime Toggle](../F014-sync-wrapper.md)

## User Story

**As an** operator running `tests/e2e/app/worker.py`
**I want** the worker CLI to honor the configured runtime mode
**So that** I can process commands using either async or sync workers without changing code.

## Context

Currently `run_worker()` always spins up async `Worker` instances and `ProcessReplyRouter`. After introducing sync wrappers and the runtime toggle, background services should mirror the selected mode: asynchronous loops when `mode=async`, blocking `SyncWorker` + `SyncProcessReplyRouter` when `mode=sync`. This story ensures CLI output and lifecycle handling reflect the active runtime.

## Acceptance Criteria

### Scenario: Async mode unchanged
**Given** runtime config is `"async"`
**When** I run `python tests/e2e/app/worker.py`
**Then** it behaves exactly as before (async workers via `asyncio.gather`)
**And** logs indicate “Runtime mode: async”.

### Scenario: Sync mode uses blocking workers
**Given** runtime config is `"sync"`
**When** I start the worker CLI
**Then** it instantiates `SyncWorker` for `e2e` and `reporting`, plus `SyncProcessReplyRouter`
**And** those components reuse the configured `thread_pool_size` (defaulting via env when omitted).

### Scenario: Graceful shutdown
**Given** sync mode is running
**When** I press Ctrl+C or send SIGINT
**Then** `SyncWorker.stop()` and router stop are invoked, thread pools shut down, and the process exits cleanly.

### Scenario: Logging shows runtime metadata
**Given** either mode is active
**When** the CLI starts
**Then** the logs include mode name and effective thread pool size for transparency.

## Technical Notes

- Update `tests/e2e/app/worker.py`:
  - Load `ConfigStore.runtime` after DB init.
  - Branch:
    - Async mode: current implementation (two `Worker`s + `ProcessReplyRouter` via `asyncio.gather`).
    - Sync mode: create shared `SyncRuntime`, build `SyncWorker`/`SyncProcessReplyRouter`, and execute `.run()` inside `asyncio.to_thread` tasks so `run_worker()` remains awaitable.
  - Implement signal handling to ensure `.stop()` is called even on cancellation.
  - Respect runtime `thread_pool_size` or fallback to env/config defaults.
- Update documentation (README, docs/e2e-test-plan) to instruct operators to restart the worker after changing runtime mode.

## Test Coverage

| Criterion | Test Type | Location |
|-----------|-----------|----------|
| Async path regression | Unit/Integration | `tests/unit/test_worker_cli.py::test_async_mode_default` |
| Sync path start/stop | Unit/Integration | `tests/unit/test_worker_cli.py::test_sync_mode_lifecycle` |
| Thread pool size override | Unit | `tests/unit/test_worker_cli.py::test_sync_thread_pool_override` |
| Manual QA instructions | Docs | `docs/e2e-test-plan.md` |

## Definition of Done

- [ ] Worker CLI inspects runtime config and branches accordingly.
- [ ] Sync path logs, thread pools, and shutdown behave as expected.
- [ ] Docs updated with restart guidance and CLI usage.
- [ ] Automated tests (or harnessable unit tests) cover both modes.
