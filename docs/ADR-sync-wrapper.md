# ADR: Synchronous Wrapper Architecture

## Status
Proposed

## Context
The Command Bus library is async-first, but many teams still build synchronous Python services (Flask, Django, scripts, CLI tools). These users either:
- Spin up their own event loops via `asyncio.run`, leading to duplicated boilerplate.
- Vault into third-party wrappers with inconsistent behavior.

We need an official synchronous mode that keeps the existing APIs and behavior in lockstep with the async core while allowing users to configure thread pool size for workers.

## Decision
Implement synchronous facades on top of the existing async core:

1. **Shared Runtime**: Introduce `SyncRuntime` that maintains a background event loop (via `asyncio.new_event_loop()` + `Thread`) and exposes `run(coro)` to block until completion.
2. **SyncCommandBus**: Wraps `CommandBus`; methods like `send`, `send_batch` call `runtime.run(...)`. No API changes for async users.
3. **SyncWorker**: Wraps `Worker` and manages a dedicated `ThreadPoolExecutor` whose size is configurable (`thread_pool_size` parameter, environment fallback). `run()` blocks until stopped, internally delegating to the async worker on the runtime loop.
4. **SyncTroubleshootingQueue** & other helpers: Provide blocking versions of TSQ operations, again calling into the async core through the runtime.
5. **Documentation & Exposure**: Export sync wrappers from `commandbus.sync` and update README with “Synchronous Usage” guidance.
6. **Testing**: Add unit tests for runtime, worker stop/start, and basic integration tests that drive the sync wrappers through the existing test suite.

This mirrors a common pattern used by libraries such as `httpx` (`Client` vs. `AsyncClient`) and `SQLAlchemy` (sync/async sessions) to support both paradigms without forking code.

## Alternatives Considered
- **Separate sync implementation**: Build a new library using blocking DB connections and queue handling. Rejected due to high maintenance cost and high risk of drift between async and sync feature sets.
- **Encourage users to wrap manually**: Rejected because many teams already struggle with deadlocks and inconsistent shutdown behavior when rolling their own wrappers.

## Consequences
### Positive
- Single source of truth for business logic, ensuring parity between async/sync consumers.
- Faster delivery: wrappers require minimal changes to the core and reuse existing tests.
- Configurable thread pools let operators tune performance.

### Negative / Risks
- Requires careful lifecycle management (background loop, executor shutdown) to avoid resource leaks.
- Synchronous callers inside async contexts must be warned to avoid deadlocks.
- Adds a small overhead for each synchronous call (futures + thread hops).

## Implementation Notes
- Provide `SyncRuntime` context manager or `shutdown()` method and register an `atexit` hook to prevent dangling threads.
- Optionally allow users to plug in their own runtime (e.g., reuse a single loop across multiple components).
- For worker thread pools, default to `min(32, os.cpu_count() or 1)` unless overridden by `COMMAND_BUS_SYNC_THREADS`.
- Code snippets and rollout plan are tracked in `docs/syncronous-python-design.md`.
