# Synchronous Mode Design

This document explores how to add a synchronous execution mode to the Command Bus library while keeping the public API surface identical wherever possible. The goal is to let applications that already use the async-first design opt into a blocking, thread-based runtime (for example, Flask/Django apps or scripts) without rewriting handlers or repositories.

## Objectives

1. **API Compatibility** – Applications should still import `CommandBus`, `Worker`, `TroubleshootingQueue`, etc. The synchronous mode can be activated through factory helpers or configuration flags but must keep method names and signatures stable (i.e., still `await bus.send()` in async code, or `bus.send()` in sync code).
2. **Shared Implementation** – Core logic (SQL, retry policies, PGMQ commands) should be reused to avoid diverging behavior. Synchronous variants should wrap asynchronous coroutines via a managed event loop or thread pool.
3. **Thread Pool Parameterization** – Workers running in synchronous mode should expose a `thread_pool_size` (default derived from CPU count) so operators can tune throughput vs. resource usage.
4. **Performance & Back Pressure** – Blocking HTTP handlers must not starve the loop. The synchronous wrapper will dedicate a thread pool to run async tasks and provide short-circuit instrumentation if the queue backs up (helpful for debugging).

## Design Overview

```
┌────────────────────────────┐            ┌────────────────────────────┐
│ Async Application (today)  │            │ Sync Application (new)     │
│                            │            │                            │
│  await bus.send(...)       │            │  bus = SyncCommandBus(...) │
│  worker = Worker(...)      │            │  worker = SyncWorker(...)  │
│  await worker.run()        │            │  worker.run()              │
└──────────────┬─────────────┘            └──────────────┬─────────────┘
               │                                         │
               ▼                                         ▼
       Async primitives                        Sync wrappers (ThreadPoolExecutor)
               │                                         │
               └────┬────────────────────────────────────┘
                    ▼
           Shared Core Components (repositories, PGMQ, retry)
```

### Key Components

1. **Loop runner utility (`commandbus.sync.runtime`)**
   - Maintains a long-lived `asyncio` event loop in a background thread using `asyncio.run` for lifecycle management.
   - Provides `run(coro)` for blocking code and `run_many(coros)` for bulk operations.

2. **`SyncCommandBus`**
   - Thin wrapper around `CommandBus`.
   - Each method (e.g., `send`, `send_batch`, `create_batch`) delegates to the async bus via `runtime.run`.
   - Keeps the same constructor signature; optional `runtime` parameter to share loops (default: global singleton).

3. **`SyncWorker`**
   - Accepts the same constructor parameters as `Worker` plus `thread_pool_size` (default `min(32, os.cpu_count() or 1)`).
   - Internally maintains a `ThreadPoolExecutor` to execute handler coroutines using `asyncio.run_coroutine_threadsafe` on a dedicated loop.
   - Public API exposes blocking `run()` and `stop()` methods. ` SyncWorker.run()` spins up a thread that calls the existing async worker and blocks until `stop()` is invoked.

4. **`SyncTroubleshootingQueue`**
   - Exposes the same methods but implemented via `SyncRuntime`. For example, `list_troubleshooting(...)` synchronously returns `list[TroubleshootingItem]`.

5. **Configuration Surface**
   - `commandbus.sync.configure(thread_pool_size: int | None = None, runtime: SyncRuntime | None = None)` helper to apply defaults globally.
   - Environment variable fallback: `COMMAND_BUS_SYNC_THREADS` if no explicit argument is provided.

## Detailed Design

### Sync Runtime

```python
# commandbus/sync/runtime.py
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Awaitable


class SyncRuntime:
    """Runs async coroutines on a dedicated event loop thread."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def run(self, coro: Awaitable[Any]) -> Any:
        """Execute coroutine synchronously and return result."""
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def shutdown(self) -> None:
        """Stop loop and join thread."""
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
```

### Sync Command Bus

```python
# commandbus/sync/bus.py
from commandbus import CommandBus
from commandbus.sync.runtime import SyncRuntime


class SyncCommandBus:
    """Blocking facade over CommandBus."""

    def __init__(self, bus: CommandBus, runtime: SyncRuntime | None = None) -> None:
        self._bus = bus
        self._runtime = runtime or SyncRuntime()

    def send(self, **kwargs):
        return self._runtime.run(self._bus.send(**kwargs))

    def send_batch(self, requests, **kwargs):
        return self._runtime.run(self._bus.send_batch(requests, **kwargs))

    # Additional blocking wrappers as needed...
```

Usage:

```python
bus = SyncCommandBus(CommandBus(pool))
result = bus.send(
    domain="reporting",
    command_type="StatementQuery",
    command_id=uuid4(),
    data={"foo": "bar"},
)
```

### Sync Worker

```python
# commandbus/sync/worker.py
from concurrent.futures import ThreadPoolExecutor

from commandbus import Worker
from commandbus.sync.runtime import SyncRuntime


class SyncWorker:
    def __init__(
        self,
        worker: Worker,
        *,
        runtime: SyncRuntime | None = None,
        thread_pool_size: int | None = None,
    ) -> None:
        self._worker = worker
        self._runtime = runtime or SyncRuntime()
        self._thread_pool = ThreadPoolExecutor(max_workers=thread_pool_size or 4)
        self._runner_thread: threading.Thread | None = None

    def run(self, *, block: bool = True) -> None:
        """Start worker loop synchronously."""
        def _target():
            self._runtime.run(self._worker.run())

        self._runner_thread = threading.Thread(target=_target, daemon=True)
        self._runner_thread.start()
        if block:
            self._runner_thread.join()

    def stop(self) -> None:
        """Signal worker to stop and wait for thread termination."""
        if self._worker.is_running:
            self._runtime.run(self._worker.stop())
        if self._runner_thread is not None:
            self._runner_thread.join(timeout=5)
        self._thread_pool.shutdown(wait=True)
```

The `Worker` class already accepts a `retry_policy` and `visibility_timeout`; in synchronous mode, we reuse those — thread pool size simply dictates how many handler executions (`handle()` coroutines) can run concurrently via the underlying async worker.

### Sync Troubleshooting Queue

```python
from commandbus.ops.troubleshooting import TroubleshootingQueue


class SyncTroubleshootingQueue:
    def __init__(self, tsq: TroubleshootingQueue, runtime: SyncRuntime | None = None) -> None:
        self._tsq = tsq
        self._runtime = runtime or SyncRuntime()

    def list_troubleshooting(self, *args, **kwargs):
        return self._runtime.run(self._tsq.list_troubleshooting(*args, **kwargs))

    def list_all_troubleshooting(self, *args, **kwargs):
        return self._runtime.run(self._tsq.list_all_troubleshooting(*args, **kwargs))

    def operator_retry(self, *args, **kwargs):
        return self._runtime.run(self._tsq.operator_retry(*args, **kwargs))
```

### Thread Pool Parameterization

The thread pool is only relevant for the synchronous worker; the bus and TSQ wrappers simply block until the async operation completes. Configuration options:

```python
worker = SyncWorker(
    Worker(pool=pool, domain="reporting", registry=registry),
    thread_pool_size=16,
)
worker.run(block=False)
```

Admins can set `COMMAND_BUS_SYNC_THREADS=16` to override the default if they do not specify a parameter.

### Error Handling & Shutdown

- `SyncRuntime` should expose `shutdown()` to stop the background loop. `SyncWorker.stop()` must call this to avoid dangling threads.
- If a synchronous API method raises an async exception, it should surface the original `CommandBusError` to the caller with context preserved (because `Future.result()` re-raises the original exception).

## Impacted Modules

1. `commandbus/sync/runtime.py` (new)
2. `commandbus/sync/bus.py` (new)
3. `commandbus/sync/worker.py` (new)
4. `commandbus/sync/tsq.py` (optional convenience)
5. `commandbus/__init__.py` – expose `SyncCommandBus`, `SyncWorker`, `SyncTroubleshootingQueue`.
6. Documentation updates: README (“Synchronous Usage”) and the new `docs/syncronous-python-design.md`.

## Testing Strategy

1. **Unit Tests**
   - Mock `SyncRuntime` to verify that synchronous wrappers call the expected async coroutines.
   - Confirm that `thread_pool_size` defaults are respected and that `stop()` drains the executor.

2. **Integration Tests**
   - Run the existing async integration suite, but instantiate `SyncCommandBus`/`SyncWorker` in a dedicated test module to ensure parity (e.g., synchronous worker can process commands successfully).

3. **Regression Testing**
   - Verify that the async path is unaffected (existing tests already cover this).

## Risks & Mitigations

- **Deadlocks** – Running blocking code on the main thread while submitting coroutines to the same thread would deadlock. Using a dedicated background loop thread avoids this.
- **Resource Exhaustion** – If synchronous workers spawn too many threads, they may overwhelm the DB. Provide clear documentation and default to a conservative pool size.
- **Shutdown Coordination** – Failing to stop the runtime thread prevents program exit. Ensure `atexit` hooks call `SyncRuntime.shutdown()`.

## Next Steps

1. Implement `SyncRuntime`, `SyncCommandBus`, `SyncWorker`, and `SyncTroubleshootingQueue`.
2. Update documentation and release notes.
3. Add integration tests that exercise the sync wrappers.
