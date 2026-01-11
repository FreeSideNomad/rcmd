# S086: Timeout Hierarchy

## User Story

As a system operator, I want layered timeouts that prevent runaway processes so that workers remain responsive and connections are not exhausted.

## Acceptance Criteria

### AC1: Statement Timeout Configuration
- Given worker processes message
- When connection acquired
- Then `SET statement_timeout = {ms}` executed

### AC2: Statement < Visibility
- Given statement_timeout=25000ms
- When visibility_timeout=30000ms
- Then statement_timeout < visibility_timeout guaranteed

### AC3: Pool Timeout
- Given pool.timeout=30
- When all connections in use
- Then PoolTimeout raised after 30 seconds

### AC4: Thread Abandon Detection
- Given message processing exceeds visibility_timeout + 5s
- When worker checks in-flight tasks
- Then stuck thread logged and slot reclaimed

### AC5: QueryCanceled Handling
- Given statement timeout triggers
- When handler receives QueryCanceled
- Then command marked as transient failure for retry

## Implementation Notes

This story integrates timeout handling across multiple components rather than creating a single new file.

**Timeout Hierarchy:**

```
┌─────────────────────────────────────────────────────────────────┐
│                    Timeout Hierarchy                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Layer 1: PostgreSQL statement_timeout (server-side)           │
│  ├── Kills query on server after N ms                          │
│  ├── Frees server resources immediately                        │
│  └── Set per-connection: SET statement_timeout = 25000         │
│                                                                 │
│  Layer 2: Connection pool timeout (client-side)                 │
│  ├── ConnectionPool(timeout=30) for getconn()                  │
│  └── Prevents indefinite wait for connections                  │
│                                                                 │
│  Layer 3: Visibility timeout (message-level)                    │
│  ├── PGMQ visibility_timeout = 30 seconds                      │
│  ├── Message reappears if not deleted                          │
│  └── statement_timeout < visibility_timeout (always)           │
│                                                                 │
│  Layer 4: Thread timeout (application-level)                    │
│  ├── Future.result(timeout=visibility_timeout + buffer)        │
│  ├── Worker can abandon stuck thread                           │
│  └── Thread may leak but worker continues                      │
│                                                                 │
│  Layer 5: Worker watchdog (supervisor-level)                    │
│  ├── Monitor thread checks worker health                       │
│  ├── Restart worker if critical state detected                 │
│  └── External: systemd/supervisor process restart              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Integration in SyncWorker._process_message():**

```python
def _process_message(self, msg: Message) -> None:
    """Process with statement timeout protection."""
    with self._pool.connection() as conn:
        # Layer 1: PostgreSQL will kill queries exceeding this
        conn.execute(
            "SET statement_timeout = %s",
            (self._statement_timeout,)
        )
        try:
            with conn.transaction():
                self._handle(msg, conn)
        except psycopg.errors.QueryCanceled:
            # statement_timeout triggered
            logger.warning(
                "Query cancelled due to timeout: %s",
                msg.command_id
            )
            self._fail_transient(msg, "TIMEOUT", "Statement timeout exceeded")
```

**Integration in SyncWorker._check_stuck_threads():**

```python
def _check_stuck_threads(self) -> None:
    """Layer 4: Identify and handle threads exceeding timeout."""
    now = time.monotonic()
    stuck_threshold = self._visibility_timeout + 5  # 5s buffer

    with self._in_flight_lock:
        for msg_id, (future, start_time) in list(self._in_flight.items()):
            elapsed = now - start_time
            if elapsed > stuck_threshold:
                logger.error(
                    "Thread stuck for %.1fs processing %s - abandoning",
                    elapsed, msg_id
                )
                # Don't cancel (may corrupt state), just stop tracking
                del self._in_flight[msg_id]
                self._health.record_stuck_thread()
```

**Pool configuration with timeout:**

```python
from psycopg_pool import ConnectionPool

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=max(4, worker_concurrency),
    max_size=min_size * 2,
    timeout=30.0,  # Layer 2: Fail-fast on exhaustion
    max_lifetime=3600.0,
    max_idle=600.0,
    check=ConnectionPool.check_connection,
    reconnect_timeout=300.0,
)
```

**Validation at Worker Init:**

```python
def __init__(self, ..., visibility_timeout: int = 30, statement_timeout: int = 25000):
    # Validate timeout hierarchy
    if statement_timeout >= visibility_timeout * 1000:
        raise ValueError(
            f"statement_timeout ({statement_timeout}ms) must be less than "
            f"visibility_timeout ({visibility_timeout}s = {visibility_timeout * 1000}ms)"
        )
```

**Estimated Lines:** ~50 (integrated into other components)
