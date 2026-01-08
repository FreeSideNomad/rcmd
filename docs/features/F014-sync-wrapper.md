# F014 - Synchronous Wrappers & Runtime Toggle

## Summary
Deliver a synchronous, thread-backed execution option for the Command Bus library and wire a runtime toggle throughout the E2E demo UI so operators can switch between async and sync behavior without touching code. This feature spans the core library (new sync runtime and facades), configuration persistence, FastAPI dependency management, and worker orchestration. Each story below is sequenced to de-risk foundational work before exposing the toggle in the UI.

## Prerequisites
- [`docs/syncronous-python-design.md`](../syncronous-python-design.md) – target design for runtime, `SyncCommandBus`, and worker wrappers.
- [`docs/ADR-sync-wrapper.md`](../ADR-sync-wrapper.md) – architectural decision record anchoring the effort.
- Feature docs referenced by downstream stories:
  - Async surfaces already in place: `src/commandbus/bus.py`, `src/commandbus/worker.py`, `src/commandbus/ops/troubleshooting.py`, `src/commandbus/process/router.py`.
  - E2E configuration + settings UI: `tests/e2e/app/api/schemas.py`, `tests/e2e/app/api/routes.py`, `tests/e2e/app/templates/pages/settings.html`, `tests/e2e/app/config.py`, `tests/e2e/app/worker.py`.

## Architecture Snapshot

```
┌───────────────┐          ┌────────────────┐
│ Async Clients │          │ Sync Clients   │
│ (current)     │          │ (new)          │
└─────┬─────────┘          └─────┬──────────┘
      │                          │
      ▼                          ▼
 ┌─────────────────┐       ┌────────────────────┐
 │ Async Primitives│◄──────┤ Sync Wrappers      │
 │ (bus, worker,   │       │ (runtime, facades) │
 │  tsq, router)   │       └────────────────────┘
 └─────────────────┘                ▲
            │                       │
            ▼                       │
     Shared repositories, retry policies, PGMQ client
```

## User Stories

| Story ID | Title | Summary |
|----------|-------|---------|
| [S069](stories/S069-sync-runtime-facades.md) | Synchronous Runtime & Facades | Introduce the `commandbus.sync` package (runtime, facades, config helper) plus unit tests and docs so library consumers can call blocking APIs without custom loop management. |
| [S070](stories/S070-runtime-config-api.md) | Runtime Configuration Persistence & API | Extend the config schemas/endpoints & `ConfigStore` to store the runtime mode and thread pool size inside `e2e.config`. |
| [S071](stories/S071-runtime-toggle-ui.md) | Settings UI Runtime Toggle | Add a Runtime Mode card to `/settings` that reads/writes the new config fields and guides operators to restart workers. |
| [S072](stories/S072-runtime-manager-fastapi.md) | Runtime-Aware FastAPI Dependency Manager | Create a runtime manager module and update FastAPI dependencies to dispatch to async vs sync implementations without changing route signatures. |
| [S073](stories/S073-runtime-aware-workers.md) | Runtime-Aware Worker & Router Orchestration | Teach `tests/e2e/app/worker.py` to branch between async workers and the new `SyncWorker`/`SyncProcessReplyRouter` using the stored mode. |
| [S074](stories/S074-sync-runtime-validation.md) | Dual-Runtime Validation & Documentation | Expand automated/manual testing plus docs/release notes to prove parity between async and sync modes. |

## Risks & Mitigations
- **Blocking FastAPI event loop.** Mitigated by routing sync calls through `asyncio.to_thread` inside the runtime manager.
- **Resource leaks.** Each story enforces explicit `shutdown()` for `SyncRuntime` and thread pools; add `atexit` safety in the core library.
- **Operator confusion.** The UI includes helper text, and README instructions clarify that workers must be restarted after changing modes.

## Follow-Ups
- Add CLI flags to override runtime mode at worker launch (useful for temporary testing without touching DB config).
- Capture performance metrics comparing async vs sync throughput and publish in a future ADR or perf appendix.
