# S080: Sync Audit Logger

## User Story

As a developer, I want a native synchronous audit logger so that sync components can record command lifecycle events.

## Acceptance Criteria

### AC1: SyncAuditLogger Class
- Given I have a sync ConnectionPool
- When I create `SyncAuditLogger(pool)`
- Then I can call sync methods: `log_send`, `log_receive`, `log_complete`

### AC2: log_send() Method
- Given a command is sent
- When I call `log_send(entry, conn=None)`
- Then SEND audit entry is recorded

### AC3: log_receive() Method
- Given a command is received by worker
- When I call `log_receive(entry, conn=None)`
- Then RECEIVE audit entry is recorded

### AC4: log_complete() Method
- Given command processing completes
- When I call `log_complete(entry, conn=None)`
- Then COMPLETE/FAILED audit entry is recorded

### AC5: Transaction Support
- Given external connection provided
- When `conn` parameter passed
- Then that connection is used for transaction participation

## Implementation Notes

**File:** `src/commandbus/sync/repositories/audit.py`

**Dependencies:**
- `src/commandbus/_core/audit_sql.py`
- `psycopg_pool.ConnectionPool`

**Code Pattern:**
```python
from psycopg_pool import ConnectionPool
from psycopg import Connection
from commandbus._core.audit_sql import AuditSQL, AuditParams
from commandbus.models import AuditEntry

class SyncAuditLogger:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def log_send(
        self,
        entry: AuditEntry,
        conn: Connection | None = None,
    ) -> None:
        sql = AuditSQL.INSERT
        params = AuditParams.from_entry(entry)

        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, params)
        else:
            with self._pool.connection() as c:
                with c.cursor() as cur:
                    cur.execute(sql, params)

    def log_receive(
        self,
        entry: AuditEntry,
        conn: Connection | None = None,
    ) -> None:
        self.log_send(entry, conn)

    def log_complete(
        self,
        entry: AuditEntry,
        conn: Connection | None = None,
    ) -> None:
        self.log_send(entry, conn)
```

**Estimated Lines:** ~80 new
