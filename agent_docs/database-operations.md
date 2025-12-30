# Database Operations Guide

Working with PostgreSQL and PGMQ in the Command Bus library.

## Connection Management

### Connection Pool Setup

```python
from psycopg_pool import AsyncConnectionPool

async def create_pool(database_url: str) -> AsyncConnectionPool:
    """Create and open a connection pool."""
    pool = AsyncConnectionPool(
        database_url,
        min_size=5,
        max_size=20,
        open=False,  # Open explicitly
    )
    await pool.open()
    return pool
```

### Lifecycle Management

```python
class DatabaseManager:
    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._pool: AsyncConnectionPool | None = None

    async def __aenter__(self) -> Self:
        self._pool = await create_pool(self._url)
        return self

    async def __aexit__(self, *args) -> None:
        if self._pool:
            await self._pool.close()

    @property
    def pool(self) -> AsyncConnectionPool:
        if not self._pool:
            raise RuntimeError("Database not connected")
        return self._pool
```

## PGMQ Operations

### Queue Management

```python
# Create a queue
await conn.execute("SELECT pgmq.create($1)", ["payments__commands"])

# Create a partitioned queue (for high volume)
await conn.execute(
    "SELECT pgmq.create_partitioned($1, $2)",
    ["events__queue", "1 day"],  # Partition by day
)

# List queues
result = await conn.execute("SELECT * FROM pgmq.list_queues()")
queues = await result.fetchall()

# Drop a queue (careful!)
await conn.execute("SELECT pgmq.drop_queue($1)", ["old_queue"])
```

### Send Messages

```python
import orjson

async def send_message(
    conn: AsyncConnection,
    queue: str,
    message: dict,
    delay: int = 0,
) -> int:
    """Send a message to the queue."""
    payload = orjson.dumps(message).decode()

    if delay > 0:
        result = await conn.execute(
            "SELECT pgmq.send($1, $2::jsonb, $3)",
            [queue, payload, delay],
        )
    else:
        result = await conn.execute(
            "SELECT pgmq.send($1, $2::jsonb)",
            [queue, payload],
        )

    row = await result.fetchone()
    return row[0]  # msg_id
```

### Read Messages

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class QueueMessage:
    msg_id: int
    read_ct: int
    enqueued_at: datetime
    vt: datetime
    message: dict

async def read_messages(
    conn: AsyncConnection,
    queue: str,
    vt: int = 30,
    limit: int = 1,
) -> list[QueueMessage]:
    """Read messages with visibility timeout."""
    result = await conn.execute(
        "SELECT * FROM pgmq.read($1, $2, $3)",
        [queue, vt, limit],
    )
    rows = await result.fetchall()

    return [
        QueueMessage(
            msg_id=row[0],
            read_ct=row[1],
            enqueued_at=row[2],
            vt=row[3],
            message=row[4],
        )
        for row in rows
    ]
```

### Message Disposition

```python
async def delete_message(conn: AsyncConnection, queue: str, msg_id: int) -> bool:
    """Delete a message (processed successfully)."""
    result = await conn.execute(
        "SELECT pgmq.delete($1, $2)",
        [queue, msg_id],
    )
    row = await result.fetchone()
    return row[0]  # True if deleted

async def archive_message(conn: AsyncConnection, queue: str, msg_id: int) -> bool:
    """Archive a message (for troubleshooting)."""
    result = await conn.execute(
        "SELECT pgmq.archive($1, $2)",
        [queue, msg_id],
    )
    row = await result.fetchone()
    return row[0]  # True if archived

async def set_visibility(
    conn: AsyncConnection,
    queue: str,
    msg_id: int,
    vt: int,
) -> datetime:
    """Extend visibility timeout (for long operations)."""
    result = await conn.execute(
        "SELECT pgmq.set_vt($1, $2, $3)",
        [queue, msg_id, vt],
    )
    row = await result.fetchone()
    return row[0]  # New VT expiration
```

### Pop (Read + Delete)

```python
async def pop_message(conn: AsyncConnection, queue: str) -> QueueMessage | None:
    """Pop a message (read and delete atomically)."""
    result = await conn.execute(
        "SELECT * FROM pgmq.pop($1)",
        [queue],
    )
    row = await result.fetchone()
    if not row:
        return None
    return QueueMessage(
        msg_id=row[0],
        read_ct=row[1],
        enqueued_at=row[2],
        vt=row[3],
        message=row[4],
    )
```

## Transactional Patterns

### Atomic Send with Metadata

```python
async def send_command_transactional(
    pool: AsyncConnectionPool,
    command: Command,
) -> int:
    """Send command with metadata in single transaction."""
    async with pool.connection() as conn:
        async with conn.transaction():
            # 1. Insert metadata (enforce uniqueness)
            await conn.execute(
                """
                INSERT INTO command_bus_command (
                    domain, command_id, command_type, status, max_attempts,
                    reply_queue, correlation_id, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
                """,
                [
                    command.domain,
                    command.command_id,
                    command.command_type,
                    "PENDING",
                    3,
                    command.reply_to,
                    command.correlation_id,
                ],
            )

            # 2. Send to PGMQ
            payload = orjson.dumps(command.to_dict()).decode()
            result = await conn.execute(
                "SELECT pgmq.send($1, $2::jsonb)",
                [f"{command.domain}__commands", payload],
            )
            msg_id = (await result.fetchone())[0]

            # 3. Update metadata with msg_id
            await conn.execute(
                """
                UPDATE command_bus_command
                SET msg_id = $1, updated_at = NOW()
                WHERE domain = $2 AND command_id = $3
                """,
                [msg_id, command.domain, command.command_id],
            )

            # 4. Audit
            await conn.execute(
                """
                INSERT INTO command_bus_audit (domain, command_id, event_type)
                VALUES ($1, $2, 'SENT')
                """,
                [command.domain, command.command_id],
            )

            return msg_id
```

### Atomic Complete

```python
async def complete_command_transactional(
    pool: AsyncConnectionPool,
    domain: str,
    command_id: UUID,
    msg_id: int,
    result_data: dict | None = None,
) -> None:
    """Complete command with reply in single transaction."""
    async with pool.connection() as conn:
        async with conn.transaction():
            # 1. Update metadata to COMPLETED
            await conn.execute(
                """
                UPDATE command_bus_command
                SET status = 'COMPLETED', updated_at = NOW()
                WHERE domain = $1 AND command_id = $2
                """,
                [domain, command_id],
            )

            # 2. Delete message from queue
            await conn.execute(
                "SELECT pgmq.delete($1, $2)",
                [f"{domain}__commands", msg_id],
            )

            # 3. Send reply
            reply = {
                "command_id": str(command_id),
                "outcome": "SUCCESS",
                "data": result_data or {},
            }
            await conn.execute(
                "SELECT pgmq.send($1, $2::jsonb)",
                [f"{domain}__replies", orjson.dumps(reply).decode()],
            )

            # 4. Audit
            await conn.execute(
                """
                INSERT INTO command_bus_audit (domain, command_id, event_type, details_json)
                VALUES ($1, $2, 'COMPLETED', $3::jsonb)
                """,
                [domain, command_id, orjson.dumps({"data": result_data}).decode()],
            )
```

## pg_notify Integration

### Sending Notifications

```python
async def notify_new_command(
    conn: AsyncConnection,
    domain: str,
    queue: str,
) -> None:
    """Notify workers of new command."""
    channel = f"commandbus.{domain}"
    await conn.execute(
        "SELECT pg_notify($1, $2)",
        [channel, queue],
    )
```

### Listening for Notifications

```python
import asyncio
from psycopg import AsyncConnection

async def listen_for_commands(
    conn: AsyncConnection,
    domain: str,
    callback: Callable[[str], Awaitable[None]],
) -> None:
    """Listen for command notifications."""
    channel = f"commandbus.{domain}"
    await conn.execute(f"LISTEN {channel}")

    async for notify in conn.notifies():
        await callback(notify.payload)
```

### Worker with Notify + Polling Fallback

```python
class NotifyWorker:
    def __init__(self, pool: AsyncConnectionPool, domain: str) -> None:
        self._pool = pool
        self._domain = domain
        self._poll_interval = 5.0  # Fallback polling

    async def run(self) -> None:
        """Run worker with notify + polling fallback."""
        async with self._pool.connection() as listen_conn:
            channel = f"commandbus.{self._domain}"
            await listen_conn.execute(f"LISTEN {channel}")

            while True:
                # Wait for notify or timeout
                try:
                    async with asyncio.timeout(self._poll_interval):
                        async for notify in listen_conn.notifies():
                            await self._process_queue(notify.payload)
                            break  # Process one, then check again
                except asyncio.TimeoutError:
                    # Fallback: poll the queue
                    await self._process_queue(f"{self._domain}__commands")

    async def _process_queue(self, queue: str) -> None:
        """Process available messages from queue."""
        async with self._pool.connection() as conn:
            messages = await read_messages(conn, queue, vt=30, limit=10)
            for msg in messages:
                await self._handle_message(msg)
```

## Query Patterns

### Find Commands by Status

```python
async def find_by_status(
    conn: AsyncConnection,
    domain: str,
    status: CommandStatus,
    limit: int = 100,
) -> list[CommandMetadata]:
    """Find commands by status."""
    result = await conn.execute(
        """
        SELECT * FROM command_bus_command
        WHERE domain = $1 AND status = $2
        ORDER BY created_at DESC
        LIMIT $3
        """,
        [domain, status.value, limit],
    )
    return [CommandMetadata.from_row(row) for row in await result.fetchall()]
```

### Get Audit Trail

```python
async def get_audit_trail(
    conn: AsyncConnection,
    command_id: UUID,
) -> list[AuditEvent]:
    """Get audit trail for a command."""
    result = await conn.execute(
        """
        SELECT event_type, ts, details_json
        FROM command_bus_audit
        WHERE command_id = $1
        ORDER BY ts ASC
        """,
        [command_id],
    )
    return [
        AuditEvent(
            event_type=row[0],
            timestamp=row[1],
            details=row[2],
        )
        for row in await result.fetchall()
    ]
```

### Queue Metrics

```python
async def get_queue_metrics(
    conn: AsyncConnection,
    queue: str,
) -> dict:
    """Get queue metrics."""
    result = await conn.execute(
        "SELECT * FROM pgmq.metrics($1)",
        [queue],
    )
    row = await result.fetchone()
    return {
        "queue_name": row[0],
        "queue_length": row[1],
        "oldest_msg_age_sec": row[2],
        "newest_msg_age_sec": row[3],
        "total_messages": row[4],
    }
```
