# S087: E2E Sync Migration

## User Story

As a developer, I want the E2E application migrated to use native sync components so that sync runtime mode no longer uses wrappers.

## Acceptance Criteria

### AC1: Remove SyncRuntime Usage
- Given current E2E uses SyncRuntime wrapper
- When sync mode selected
- Then native SyncWorker used instead

### AC2: Remove Concurrency Cap Workaround
- Given current code caps `concurrency=min(original, 2)`
- When native sync worker used
- Then full concurrency supported

### AC3: Remove Magic Multipliers
- Given WORKER_CONNECTION_MULTIPLIER=5, etc.
- When native sync used
- Then pool sized simply as `min_size=concurrency`

### AC4: Sync Pool Creation
- Given sync mode selected
- When pool created
- Then `psycopg_pool.ConnectionPool` (sync) used, not AsyncConnectionPool

### AC5: Handler Compatibility
- Given existing handlers
- When sync worker dispatches
- Then handlers execute in sync context

### AC6: Health Endpoint
- Given sync workers running
- When /health/ready queried
- Then worker health status returned

## Implementation Notes

**Files to Modify:**
- `tests/e2e/app/worker.py` - Major refactor
- `tests/e2e/app/dependencies.py` - Add sync factories

**Current Problem Areas in tests/e2e/app/worker.py:**

```python
# REMOVE: Magic multipliers
WORKER_CONNECTION_MULTIPLIER = 5
ROUTER_CONNECTION_MULTIPLIER = 3

# REMOVE: Forced concurrency cap
if runtime_mode == "sync":
    original_sync_concurrency = worker_config.concurrency
    worker_config = replace(worker_config, concurrency=min(original_sync_concurrency, 2))

# REMOVE: SyncRuntime usage
sync_runtime = SyncRuntime()
sync_e2e = SyncWorker(
    worker=base_e2e_worker,
    runtime=sync_runtime,
    thread_pool_size=thread_pool_size,
)
```

**New Implementation Pattern:**

```python
from psycopg_pool import ConnectionPool
from commandbus.sync.worker import SyncWorker as NativeSyncWorker
from commandbus.sync.process.router import SyncProcessReplyRouter as NativeSyncRouter
from commandbus.sync.health import HealthStatus

async def run_worker(shutdown_event: asyncio.Event | None = None) -> None:
    # ... setup code ...

    if runtime_mode == "sync":
        # Create sync pool (not async)
        sync_pool = ConnectionPool(
            conninfo=Config.DATABASE_URL,
            min_size=max(4, worker_config.concurrency),
            max_size=max(8, worker_config.concurrency * 2),
            timeout=30.0,
            open=False,
        )
        sync_pool.open()

        try:
            # Create native sync workers
            sync_e2e = NativeSyncWorker(
                pool=sync_pool,
                domain="e2e",
                registry=registry,
                concurrency=worker_config.concurrency,
                poll_interval=worker_config.poll_interval,
                visibility_timeout=worker_config.visibility_timeout,
            )
            sync_reporting = NativeSyncWorker(
                pool=sync_pool,
                domain="reporting",
                registry=registry,
                concurrency=worker_config.concurrency,
                poll_interval=worker_config.poll_interval,
                visibility_timeout=worker_config.visibility_timeout,
            )

            # Create native sync router
            sync_router = NativeSyncRouter(
                pool=sync_pool,
                process_repo=SyncProcessRepository(sync_pool),
                managers=managers,
                reply_queue="reporting__process_replies",
                domain="reporting",
                concurrency=worker_config.concurrency,
            )

            # Run in threads (native sync, no asyncio wrappers)
            await _run_native_sync_services(
                workers=(sync_e2e, sync_reporting),
                router=sync_router,
                stop_event=stop_event,
            )
        finally:
            sync_pool.close()
    else:
        # Existing async path unchanged
        await _run_async_services(...)


async def _run_native_sync_services(
    *,
    workers: Sequence[NativeSyncWorker],
    router: NativeSyncRouter,
    stop_event: asyncio.Event,
) -> None:
    """Run native sync workers in threads."""
    import threading

    threads: list[threading.Thread] = []

    # Start workers in threads
    for worker in workers:
        t = threading.Thread(target=worker.run, name=f"sync-{worker._domain}")
        t.start()
        threads.append(t)

    # Start router in thread
    router_thread = threading.Thread(target=router.run, name="sync-router")
    router_thread.start()
    threads.append(router_thread)

    # Wait for stop signal
    await stop_event.wait()

    # Stop all workers
    for worker in workers:
        worker.stop()
    router.stop()

    # Wait for threads to complete
    for t in threads:
        t.join(timeout=30)
```

**Health Endpoint Integration:**

```python
# tests/e2e/app/api/routes.py
from fastapi import Response

@router.get("/health/ready")
def health_ready():
    """Readiness check based on worker health."""
    # Get worker health from shared state
    health = get_worker_health()

    if health.state == HealthState.CRITICAL:
        return Response(
            content='{"status": "critical"}',
            status_code=503,
            media_type="application/json",
        )
    elif health.state == HealthState.DEGRADED:
        return Response(
            content='{"status": "degraded"}',
            status_code=200,
            media_type="application/json",
        )
    return {"status": "healthy"}
```

**Estimated Lines:** ~200 modified
