# Code Patterns

Preferred implementation patterns for the Command Bus library.

## Repository Pattern

All database operations go through repository interfaces.

### Protocol Definition

```python
# src/commandbus/repositories/base.py
from typing import Protocol
from uuid import UUID
from psycopg import AsyncConnection

from commandbus.models import CommandMetadata

class CommandRepository(Protocol):
    """Repository for command metadata."""

    async def save(
        self,
        command: CommandMetadata,
        *,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Save command metadata."""
        ...

    async def get_by_id(
        self,
        domain: str,
        command_id: UUID,
        *,
        conn: AsyncConnection | None = None,
    ) -> CommandMetadata | None:
        """Get command by domain and ID."""
        ...

    async def update_status(
        self,
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        *,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Update command status."""
        ...
```

### Implementation

```python
# src/commandbus/repositories/postgres.py
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

class PostgresCommandRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def save(
        self,
        command: CommandMetadata,
        *,
        conn: AsyncConnection | None = None,
    ) -> None:
        sql = """
            INSERT INTO command_bus_command (
                domain, command_id, command_type, status, ...
            ) VALUES ($1, $2, $3, $4, ...)
        """
        async with self._get_connection(conn) as c:
            await c.execute(sql, (command.domain, command.command_id, ...))

    @asynccontextmanager
    async def _get_connection(
        self, conn: AsyncConnection | None
    ) -> AsyncIterator[AsyncConnection]:
        if conn is not None:
            yield conn
        else:
            async with self._pool.connection() as c:
                yield c
```

## Transaction Management

Use context managers for explicit transaction boundaries.

### Transactional Operations

```python
async def send(self, command: Command) -> UUID:
    """Send a command atomically with metadata."""
    async with self._pool.connection() as conn:
        async with conn.transaction():
            # All operations in same transaction
            await self._repo.save(command.metadata, conn=conn)
            msg_id = await self._pgmq.send(
                command.queue,
                command.payload,
                conn=conn,
            )
            await self._repo.update_msg_id(
                command.domain,
                command.command_id,
                msg_id,
                conn=conn,
            )
            await self._audit.log(
                event_type="SENT",
                command_id=command.command_id,
                conn=conn,
            )
    return command.command_id
```

## Result Types for Errors

Use dataclasses or typed results instead of raising exceptions for expected outcomes.

### Result Pattern

```python
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

@dataclass(frozen=True, slots=True)
class Success(Generic[T]):
    value: T

@dataclass(frozen=True, slots=True)
class Failure:
    code: str
    message: str
    details: dict[str, Any] | None = None

Result = Success[T] | Failure

# Usage
async def validate_command(cmd: Command) -> Result[Command]:
    if not cmd.data:
        return Failure(code="EMPTY_DATA", message="Command data is required")
    return Success(cmd)
```

## Handler Registry

Decouple handler registration from execution.

```python
HandlerFn = Callable[[Command, HandlerContext], Awaitable[Any]]

class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], HandlerFn] = {}

    def register(
        self,
        domain: str,
        command_type: str,
        handler: HandlerFn,
    ) -> None:
        key = (domain, command_type)
        if key in self._handlers:
            raise ValueError(f"Handler already registered for {domain}.{command_type}")
        self._handlers[key] = handler

    def get(self, domain: str, command_type: str) -> HandlerFn | None:
        return self._handlers.get((domain, command_type))

    def decorator(
        self,
        domain: str,
        command_type: str,
    ) -> Callable[[HandlerFn], HandlerFn]:
        def wrapper(fn: HandlerFn) -> HandlerFn:
            self.register(domain, command_type, fn)
            return fn
        return wrapper
```

## Worker Loop Pattern

Clean shutdown and error handling.

```python
class Worker:
    def __init__(
        self,
        *,
        domain: str,
        bus: CommandBus,
        concurrency: int = 10,
        vt_seconds: int = 30,
    ) -> None:
        self._domain = domain
        self._bus = bus
        self._concurrency = concurrency
        self._vt_seconds = vt_seconds
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def run(self) -> None:
        """Run the worker until stopped."""
        self._running = True
        try:
            async with asyncio.TaskGroup() as tg:
                for _ in range(self._concurrency):
                    tg.create_task(self._worker_loop())
        except* Exception as eg:
            for exc in eg.exceptions:
                logger.error("Worker error", exc_info=exc)
            raise

    async def stop(self, timeout: float = 30.0) -> None:
        """Gracefully stop the worker."""
        self._running = False
        self._shutdown_event.set()
        # Wait for in-flight work to complete

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                messages = await self._bus.receive(
                    self._domain,
                    vt=self._vt_seconds,
                    limit=1,
                )
                for msg in messages:
                    await self._process_message(msg)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in worker loop")
                await asyncio.sleep(1)  # Backoff on error
```

## Logging Pattern

Structured logging with context.

```python
import logging
from contextvars import ContextVar

# Context for request tracing
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()
        return True

# Setup
logger = logging.getLogger("commandbus")
logger.addFilter(ContextFilter())

# Usage in handler
async def process_command(cmd: Command) -> None:
    token = correlation_id_var.set(str(cmd.correlation_id))
    try:
        logger.info(
            "Processing command",
            extra={
                "command_id": str(cmd.command_id),
                "command_type": cmd.command_type,
            },
        )
        # ... process
    finally:
        correlation_id_var.reset(token)
```

## Configuration Pattern

Immutable configuration with validation.

```python
from dataclasses import dataclass
from typing import Self
import os

@dataclass(frozen=True, slots=True)
class Config:
    database_url: str
    max_retries: int = 3
    vt_seconds: int = 30
    backoff_base: float = 10.0
    backoff_multiplier: float = 2.0
    max_backoff: float = 300.0

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            database_url=os.environ["DATABASE_URL"],
            max_retries=int(os.environ.get("MAX_RETRIES", "3")),
            vt_seconds=int(os.environ.get("VT_SECONDS", "30")),
        )

    def __post_init__(self) -> None:
        if self.max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if self.vt_seconds < 5:
            raise ValueError("vt_seconds must be >= 5")
```
