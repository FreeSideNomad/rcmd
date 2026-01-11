# S079: Sync Process Repository

## User Story

As a developer, I want a native synchronous process repository so that sync components can persist and query process state and audit trails.

## Acceptance Criteria

### AC1: SyncProcessRepository Class
- Given I have a sync ConnectionPool
- When I create `SyncProcessRepository(pool)`
- Then I can call sync methods: `save`, `update`, `get_by_id`, `log_step`, `get_audit_trail`

### AC2: save() Method
- Given a new ProcessMetadata
- When I call `save(process, conn=None)`
- Then process is inserted into commandbus.process table

### AC3: update() Method
- Given process state changes
- When I call `update(process, conn=None)`
- Then process row is updated and updated_at is set

### AC4: get_by_id() Method
- Given a domain and process_id
- When I call `get_by_id(domain, process_id, conn=None)`
- Then I get `ProcessMetadata | None` with deserialized state

### AC5: log_step() Method
- Given a step is executed
- When I call `log_step(domain, process_id, entry, conn=None)`
- Then entry is inserted into commandbus.process_audit

### AC6: get_audit_trail() Method
- Given process has executed steps
- When I call `get_audit_trail(domain, process_id, conn=None)`
- Then I get list of ProcessAuditEntry ordered by sent_at

## Implementation Notes

**File:** `src/commandbus/sync/process/repository.py`

**Dependencies:**
- `src/commandbus/_core/process_sql.py`
- `psycopg_pool.ConnectionPool`

**Code Pattern:**
```python
from psycopg_pool import ConnectionPool
from psycopg import Connection
from commandbus._core.process_sql import ProcessSQL, ProcessParams, ProcessParsers
from commandbus.process.models import ProcessMetadata, ProcessAuditEntry

class SyncProcessRepository:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def save(
        self,
        process: ProcessMetadata,
        conn: Connection | None = None,
    ) -> None:
        sql = ProcessSQL.SAVE
        params = ProcessParams.save(process)

        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, params)
        else:
            with self._pool.connection() as c:
                with c.cursor() as cur:
                    cur.execute(sql, params)

    def get_by_id(
        self,
        domain: str,
        process_id: UUID,
        conn: Connection | None = None,
    ) -> ProcessMetadata | None:
        sql = ProcessSQL.GET
        params = ProcessParams.get(domain, process_id)

        def _execute(c: Connection) -> ProcessMetadata | None:
            with c.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                if row is None:
                    return None
                return ProcessParsers.from_row(row)

        if conn is not None:
            return _execute(conn)
        else:
            with self._pool.connection() as c:
                return _execute(c)

    def log_step(
        self,
        domain: str,
        process_id: UUID,
        entry: ProcessAuditEntry,
        conn: Connection | None = None,
    ) -> None:
        sql = ProcessSQL.LOG_STEP
        params = ProcessParams.log_step(domain, process_id, entry)

        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, params)
        else:
            with self._pool.connection() as c:
                with c.cursor() as cur:
                    cur.execute(sql, params)
```

**Estimated Lines:** ~150 new
