# S078: Sync Batch Repository

## User Story

As a developer, I want a native synchronous batch repository so that sync components can create and manage command batches.

## Acceptance Criteria

### AC1: SyncBatchRepository Class
- Given I have a sync ConnectionPool
- When I create `SyncBatchRepository(pool)`
- Then I can call sync methods: `create`, `get`, `update_count`, `mark_complete`

### AC2: create() Method
- Given batch metadata
- When I call `create(batch, conn=None)`
- Then batch is persisted to database

### AC3: get() Method
- Given a domain and batch_id
- When I call `get(domain, batch_id, conn=None)`
- Then I get `BatchMetadata | None`

### AC4: update_count() Method
- Given batch processing updates
- When I call `update_count(domain, batch_id, completed, failed, conn=None)`
- Then batch counters are updated

### AC5: mark_complete() Method
- Given all batch commands processed
- When I call `mark_complete(domain, batch_id, status, conn=None)`
- Then batch status set and completed_at timestamp set

### AC6: Transaction Support
- Given external connection provided
- When `conn` parameter passed
- Then that connection is used for transaction participation

## Implementation Notes

**File:** `src/commandbus/sync/repositories/batch.py`

**Dependencies:**
- `src/commandbus/_core/batch_sql.py`
- `psycopg_pool.ConnectionPool`

**Code Pattern:**
```python
from psycopg_pool import ConnectionPool
from psycopg import Connection
from commandbus._core.batch_sql import BatchSQL, BatchParams, BatchParsers
from commandbus.models import BatchMetadata, BatchStatus

class SyncBatchRepository:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def create(
        self,
        batch: BatchMetadata,
        conn: Connection | None = None,
    ) -> None:
        sql = BatchSQL.CREATE
        params = BatchParams.create(batch)

        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, params)
        else:
            with self._pool.connection() as c:
                with c.cursor() as cur:
                    cur.execute(sql, params)

    def get(
        self,
        domain: str,
        batch_id: UUID,
        conn: Connection | None = None,
    ) -> BatchMetadata | None:
        sql = BatchSQL.GET
        params = BatchParams.get(domain, batch_id)

        def _execute(c: Connection) -> BatchMetadata | None:
            with c.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                if row is None:
                    return None
                return BatchParsers.from_row(row)

        if conn is not None:
            return _execute(conn)
        else:
            with self._pool.connection() as c:
                return _execute(c)
```

**Estimated Lines:** ~100 new
