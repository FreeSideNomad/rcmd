# S076: Sync PGMQ Client

## User Story

As a developer, I want a native synchronous PGMQ client that uses psycopg3's sync `ConnectionPool` so that sync workers can interact with PGMQ without async overhead.

## Acceptance Criteria

### AC1: SyncPgmqClient Class
- Given I have a sync ConnectionPool
- When I create `SyncPgmqClient(pool)`
- Then I can call sync methods: `send`, `read`, `delete`, `archive`, `set_vt`

### AC2: send() Method
- Given a message payload
- When I call `send(queue, payload, delay=0, conn=None)`
- Then message is enqueued and msg_id returned

### AC3: read() Method
- Given messages in queue
- When I call `read(queue, vt=30, limit=1, conn=None)`
- Then I get list of `PgmqMessage` dataclasses

### AC4: delete() Method
- Given a message ID
- When I call `delete(queue, msg_id, conn=None)`
- Then message is removed from queue

### AC5: read_with_poll() Method
- Given empty queue
- When I call `read_with_poll(queue, vt, limit, poll_interval, max_wait)`
- Then it polls until messages available or max_wait exceeded

### AC6: Uses Shared Core
- Given `_core.pgmq_sql` exists
- When SyncPgmqClient executes SQL
- Then it uses `PgmqSQL.SEND`, `PgmqSQL.READ`, etc.

## Implementation Notes

**File:** `src/commandbus/sync/pgmq.py`

**Dependencies:**
- `src/commandbus/_core/pgmq_sql.py`
- `psycopg_pool.ConnectionPool`

**Code Pattern:**
```python
from psycopg_pool import ConnectionPool
from psycopg import Connection
from commandbus._core.pgmq_sql import PgmqSQL, PgmqParams, PgmqParsers

class SyncPgmqClient:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def send(
        self,
        queue: str,
        payload: dict,
        delay: int = 0,
        conn: Connection | None = None,
    ) -> int:
        sql = PgmqSQL.SEND
        params = PgmqParams.send(queue, payload, delay)

        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()[0]
        else:
            with self._pool.connection() as c:
                with c.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchone()[0]

    def read(
        self,
        queue: str,
        vt: int = 30,
        limit: int = 1,
        conn: Connection | None = None,
    ) -> list[PgmqMessage]:
        sql = PgmqSQL.READ
        params = PgmqParams.read(queue, vt, limit)

        def _execute(c: Connection) -> list[PgmqMessage]:
            with c.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [PgmqParsers.from_row(row) for row in rows]

        if conn is not None:
            return _execute(conn)
        else:
            with self._pool.connection() as c:
                return _execute(c)

    def delete(
        self,
        queue: str,
        msg_id: int,
        conn: Connection | None = None,
    ) -> bool:
        sql = PgmqSQL.DELETE
        params = PgmqParams.delete(queue, msg_id)

        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()[0]
        else:
            with self._pool.connection() as c:
                with c.cursor() as cur:
                    cur.execute(sql, params)
                    return cur.fetchone()[0]
```

**Estimated Lines:** ~150 new
