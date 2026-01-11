# S077: Sync Command Repository

## User Story

As a developer, I want a native synchronous command repository that provides the same interface as the async version so that sync components can persist and query commands.

## Acceptance Criteria

### AC1: SyncCommandRepository Class
- Given I have a sync ConnectionPool
- When I create `SyncCommandRepository(pool)`
- Then I can call sync methods: `save`, `get_by_id`, `update_status`, `find_by_batch`

### AC2: save() Method
- Given a CommandMetadata
- When I call `save(metadata, queue_name, conn=None)`
- Then command is persisted to database

### AC3: get_by_id() Method
- Given a domain and command_id
- When I call `get_by_id(domain, command_id, conn=None)`
- Then I get `CommandMetadata | None`

### AC4: receive_command() Method
- Given commands waiting in queue
- When I call `receive_command(domain, batch_size, vt)`
- Then stored procedure is called and tuple returned

### AC5: finish_command() Method
- Given command processing complete
- When I call `finish_command(domain, command_id, status, error_code, error_msg)`
- Then command status updated and message handled

### AC6: Transaction Support
- Given external connection provided
- When `conn` parameter passed to any method
- Then that connection is used (for transaction participation)

## Implementation Notes

**File:** `src/commandbus/sync/repositories/command.py`

**Dependencies:**
- `src/commandbus/_core/command_sql.py`
- `psycopg_pool.ConnectionPool`

**Code Pattern:**
```python
from psycopg_pool import ConnectionPool
from psycopg import Connection
from commandbus._core.command_sql import CommandSQL, CommandParams, CommandParsers
from commandbus.models import CommandMetadata, CommandStatus

class SyncCommandRepository:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def save(
        self,
        metadata: CommandMetadata,
        queue_name: str,
        conn: Connection | None = None,
    ) -> None:
        sql = CommandSQL.SAVE
        params = CommandParams.save(metadata, queue_name)

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
        command_id: UUID,
        conn: Connection | None = None,
    ) -> CommandMetadata | None:
        sql = CommandSQL.GET
        params = CommandParams.get(domain, command_id)

        def _execute(c: Connection) -> CommandMetadata | None:
            with c.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                if row is None:
                    return None
                return CommandParsers.from_row(row)

        if conn is not None:
            return _execute(conn)
        else:
            with self._pool.connection() as c:
                return _execute(c)

    def update_status(
        self,
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        error_code: str | None = None,
        error_message: str | None = None,
        conn: Connection | None = None,
    ) -> None:
        sql = CommandSQL.UPDATE_STATUS
        params = CommandParams.update_status(
            domain, command_id, status, error_code, error_message
        )

        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, params)
        else:
            with self._pool.connection() as c:
                with c.cursor() as cur:
                    cur.execute(sql, params)
```

**Estimated Lines:** ~250 new
