# F015: Native Synchronous Runtime

## Summary

Replace async-wrapper sync implementation with native synchronous components using psycopg3's thread-safe `ConnectionPool`, eliminating connection pool exhaustion and enabling predictable resource usage.

## Motivation

The current sync implementation wraps async code with `SyncRuntime.run()` which:
1. Runs a background event loop thread
2. Uses `asyncio.run_coroutine_threadsafe()` for each operation
3. Holds connections across await points when blocked by sync threads

This causes connection pool exhaustion because async code assumes cooperative multitasking where tasks yield connections during I/O waits. Sync wrappers block threads, holding connections for entire operation durations.

**Evidence from recent commits:**
| Commit | Issue | Root Cause |
|--------|-------|------------|
| `6ee00af` | Throttle sync worker concurrency | Pool exhaustion |
| `7d14c0d` | Auto-cap pool based on server limits | Connection starvation |
| `7379b37` | Cap sync worker concurrency based on pool | Threading/pool mismatch |
| `2080369` | Right-size worker DB pool | Async assumptions invalid for sync |
| `eb4a5fa` | Improve sync worker diagnostics | Silent failures |

## User Stories

### Core Infrastructure
- [S075](stories/S075-shared-sql-core.md) - Extract shared SQL constants and parsers
- [S076](stories/S076-sync-pgmq-client.md) - Native sync PGMQ client
- [S077](stories/S077-sync-command-repository.md) - Native sync command repository
- [S078](stories/S078-sync-batch-repository.md) - Native sync batch repository
- [S079](stories/S079-sync-process-repository.md) - Native sync process repository
- [S080](stories/S080-sync-audit-logger.md) - Native sync audit logger

### Orchestration Layer
- [S081](stories/S081-sync-command-bus.md) - Native sync command bus
- [S082](stories/S082-sync-worker.md) - Native sync worker with ThreadPoolExecutor
- [S083](stories/S083-sync-process-router.md) - Native sync process reply router

### Health & Recovery
- [S084](stories/S084-health-status-tracking.md) - Worker health status tracking
- [S085](stories/S085-worker-watchdog.md) - Worker watchdog and self-recovery
- [S086](stories/S086-timeout-hierarchy.md) - Multi-layer timeout implementation

### Migration & Cleanup
- [S087](stories/S087-e2e-sync-migration.md) - E2E app sync runtime migration
- [S088](stories/S088-remove-sync-wrappers.md) - Remove old sync wrapper code

## Acceptance Criteria (Feature-Level)

- [ ] Connection usage: `connections_held = worker_concurrency` (not multiplied)
- [ ] No connection pool exhaustion under normal load (concurrency up to 16)
- [ ] Clean shutdown within 30 seconds
- [ ] Self-recovery from degraded states without manual intervention
- [ ] Health endpoints for Kubernetes probes (liveness/readiness)
- [ ] Performance within 10% of async mode for equivalent workload
- [ ] 80% test coverage on all new sync components

## Technical Design

### Architecture (Hybrid Approach - Option E)

```
src/commandbus/
├── _core/                      # Shared logic (NEW)
│   ├── __init__.py
│   ├── command_sql.py          # SQL constants + param builders + parsers
│   ├── batch_sql.py            # Batch SQL logic
│   ├── process_sql.py          # Process SQL logic
│   └── pgmq_sql.py             # PGMQ SQL logic
│
├── repositories/               # Async implementations (refactored)
│   ├── command.py              # Uses _core, async I/O
│   ├── audit.py                # Uses _core
│   └── batch.py                # Uses _core
│
├── pgmq/
│   └── client.py               # Async PGMQ, uses _core
│
├── worker.py                   # Async worker (unchanged)
├── bus.py                      # Async bus
│
└── sync/                       # Sync implementations
    ├── __init__.py             # Public exports
    ├── pool.py                 # Pool configuration helpers
    ├── repositories/
    │   ├── __init__.py
    │   ├── command.py          # Uses _core, sync I/O
    │   ├── audit.py
    │   └── batch.py
    ├── pgmq.py                 # Sync PGMQ, uses _core
    ├── worker.py               # Native sync worker (ThreadPoolExecutor)
    ├── bus.py                  # Native sync bus
    ├── health.py               # HealthStatus, HealthState
    ├── watchdog.py             # WorkerWatchdog
    └── process/
        ├── __init__.py
        ├── repository.py       # Sync process repository
        └── router.py           # Native sync router
```

### Connection Pool Configuration

```python
from psycopg_pool import ConnectionPool

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=max(4, worker_concurrency),
    max_size=min_size * 2,
    timeout=30.0,                  # Fail-fast on exhaustion
    max_lifetime=3600.0,           # 1 hour max connection age
    max_idle=600.0,                # 10 min idle before close
    check=ConnectionPool.check_connection,
    reconnect_timeout=300.0,       # 5 min reconnection attempts
)
```

### Timeout Hierarchy

```
Layer 1: PostgreSQL statement_timeout (25s)
    └── Kills query on server, frees resources
Layer 2: Connection pool timeout (30s)
    └── Fail-fast on pool exhaustion
Layer 3: PGMQ visibility_timeout (30s)
    └── Message reappears if not deleted
Layer 4: Thread timeout (35s)
    └── Worker can abandon stuck thread
Layer 5: Worker watchdog (60s)
    └── Monitor and restart unhealthy workers
```

### Sync Worker Architecture

```python
class SyncWorker:
    def __init__(
        self,
        pool: ConnectionPool,
        domain: str,
        registry: HandlerRegistry,
        *,
        concurrency: int = 4,
        poll_interval: float = 1.0,
        visibility_timeout: int = 30,
        statement_timeout: int = 25000,
    ):
        self._executor: ThreadPoolExecutor | None = None
        self._stop_event = threading.Event()
        self._in_flight: dict[str, Future] = {}
        self._health_status = HealthStatus()

    def run(self) -> None:
        """Main worker loop - blocks until stop() called."""
        self._executor = ThreadPoolExecutor(
            max_workers=self._concurrency,
            thread_name_prefix=f"worker-{self._domain}",
        )
        try:
            while not self._stop_event.is_set():
                self._poll_and_dispatch()
        finally:
            self._drain_in_flight()
            self._executor.shutdown(wait=True)

    def _process_message(self, msg: Message) -> None:
        """Process with dedicated connection and statement timeout."""
        with self._pool.connection() as conn:
            conn.execute(f"SET statement_timeout = {self._statement_timeout}")
            with conn.transaction():
                # ... handle message ...
```

### Health Status States

```
HEALTHY → (failures > 10) → DEGRADED
HEALTHY → (stuck_threads > 3 OR pool_exhaustions > 5) → CRITICAL
CRITICAL → (watchdog triggers) → Worker restart
```

## Dependencies

- F001: Command Sending
- F002: Command Processing
- F004: Troubleshooting Queue
- F009: Batch Commands
- F013: Process Manager

## Out of Scope

- Async/sync handler interoperability (handlers must match runtime)
- ProcessPoolExecutor option (ThreadPoolExecutor sufficient)
- Custom reconnection strategies beyond psycopg3 defaults

## Implementation Milestones

- [ ] Milestone 1: Shared SQL core extraction (_core/)
- [ ] Milestone 2: Sync repositories (using _core)
- [ ] Milestone 3: Sync PGMQ client
- [ ] Milestone 4: Sync CommandBus
- [ ] Milestone 5: Sync Worker (native ThreadPoolExecutor)
- [ ] Milestone 6: Sync ProcessReplyRouter
- [ ] Milestone 7: Health status and watchdog
- [ ] Milestone 8: E2E migration and wrapper cleanup

## LLM Agent Notes

**Reference Files:**
- `docs/sync-refactoring-plan.md` - Full design specification
- `docs/sync-code-deduplication-options.md` - Option analysis (selected E)
- `src/commandbus/repositories/command.py` - Current async repo (~950 lines)
- `src/commandbus/worker.py` - Current async worker (~800 lines)
- `src/commandbus/sync/runtime.py` - Current wrapper (TO BE REMOVED)
- `tests/e2e/app/worker.py` - E2E worker integration

**Patterns to Follow:**
- SQL constants as class attributes in _core modules
- Parameter builders as @staticmethod methods
- Row parsers returning typed dataclasses
- Context managers for connection handling
- ThreadPoolExecutor for sync concurrency

**Key Constraints:**
- `statement_timeout < visibility_timeout` (always)
- Connection pool `min_size >= worker_concurrency`
- Thread names: `worker-{domain}-{n}` for debugging
- Health status thread-safe with Lock

**Testing Strategy:**
- Unit tests: Mock ConnectionPool, test core logic
- Integration tests: Real PostgreSQL, test full flow
- E2E tests: Worker lifecycle, shutdown, recovery
