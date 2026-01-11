# Sync Implementation: Code Deduplication Options

## Problem Statement

Implementing native sync versions of all components risks significant code duplication:

| Component | Lines of Code | Duplication Risk |
|-----------|---------------|------------------|
| `worker.py` | ~800 | High (concurrency logic) |
| `repositories/command.py` | ~950 | Medium (SQL same, I/O differs) |
| `pgmq/client.py` | ~350 | Medium (SQL same) |
| `process/router.py` | ~280 | High (similar to worker) |
| `process/base.py` | ~400 | Medium (orchestration logic) |
| `bus.py` | ~350 | Low (thin wrapper) |
| **Total** | ~3,130 | **~2,000 lines at risk** |

This document presents four architectural options with trade-offs.

---

## Option A: Shared SQL Layer with Runtime Adapters

### Concept

Extract SQL strings and parameter building into a **shared core**, then create thin async/sync adapters that only differ in connection handling.

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Code                                     │
│         (uses AsyncCommandRepository or SyncCommandRepository)   │
└────────────────────────────┬────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                                       ▼
┌─────────────────────┐               ┌─────────────────────┐
│ AsyncCommandRepository│             │ SyncCommandRepository│
│  (async with conn)    │             │  (with conn)         │
└──────────┬────────────┘             └──────────┬──────────┘
           │                                     │
           └─────────────────┬───────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CommandRepositoryCore                         │
│  - SQL strings (class constants)                                 │
│  - Parameter builders: build_save_params(metadata) -> tuple     │
│  - Result parsers: parse_command_row(row) -> CommandMetadata    │
│  - Validation logic (no I/O)                                    │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation Example

```python
# commandbus/repositories/_core/command.py
class CommandRepositoryCore:
    """Shared SQL and logic for command repository."""

    # SQL as class constants
    SAVE_SQL = """
        INSERT INTO commandbus.command (
            domain, queue_name, msg_id, command_id, command_type,
            status, attempts, max_attempts, correlation_id, reply_queue,
            created_at, updated_at, batch_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    GET_SQL = """
        SELECT domain, queue_name, msg_id, command_id, command_type,
               status, attempts, max_attempts, correlation_id, reply_queue,
               created_at, updated_at, completed_at, error_code, error_message,
               batch_id
        FROM commandbus.command
        WHERE domain = %s AND command_id = %s
    """

    @staticmethod
    def build_save_params(metadata: CommandMetadata, queue_name: str) -> tuple:
        """Build parameters for SAVE_SQL."""
        return (
            metadata.domain,
            queue_name,
            metadata.msg_id,
            metadata.command_id,
            metadata.command_type,
            metadata.status.value,
            metadata.attempts,
            metadata.max_attempts,
            metadata.correlation_id,
            metadata.reply_to or "",
            metadata.created_at,
            metadata.updated_at,
            metadata.batch_id,
        )

    @staticmethod
    def parse_command_row(row: tuple) -> CommandMetadata:
        """Parse database row into CommandMetadata."""
        return CommandMetadata(
            domain=row[0],
            # ... rest of parsing
        )


# commandbus/repositories/command.py (async)
class PostgresCommandRepository:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool
        self._core = CommandRepositoryCore()

    async def save(self, metadata: CommandMetadata, queue_name: str, conn=None):
        sql = self._core.SAVE_SQL
        params = self._core.build_save_params(metadata, queue_name)
        if conn:
            await conn.execute(sql, params)
        else:
            async with self._pool.connection() as c:
                await c.execute(sql, params)


# commandbus/sync/repositories/command.py (sync)
class SyncCommandRepository:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool
        self._core = CommandRepositoryCore()

    def save(self, metadata: CommandMetadata, queue_name: str, conn=None):
        sql = self._core.SAVE_SQL
        params = self._core.build_save_params(metadata, queue_name)
        if conn:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)
```

### Pros

- **Minimal duplication**: SQL and parsing logic shared (~60-70% code reuse)
- **Type safety preserved**: Both variants are fully typed
- **Easy maintenance**: SQL changes in one place
- **Clear separation**: I/O adapters are thin and obvious
- **Testable core**: Core logic unit-testable without database

### Cons

- **More files**: Core + async + sync for each component
- **Indirection**: Extra layer to navigate
- **Doesn't help Worker/Router**: Their complexity is in concurrency, not SQL

### Duplication Reduction

| Component | Original | With Option A | Reduction |
|-----------|----------|---------------|-----------|
| Repositories (~1,700 lines) | 100% | ~35% | **65%** |
| PGMQ Client (~350 lines) | 100% | ~30% | **70%** |
| Worker (~800 lines) | 100% | ~90% | 10% |
| Router (~280 lines) | 100% | ~90% | 10% |
| **Total** | 3,130 | ~1,800 | **~42%** |

---

## Option B: Generic Connection Abstraction

### Concept

Create a connection abstraction that works for both sync and async, using generics and protocols.

```python
from typing import TypeVar, Protocol, Generic, ContextManager, AsyncContextManager

TConn = TypeVar("TConn")  # Connection type
TPool = TypeVar("TPool")  # Pool type

class ConnectionProvider(Protocol[TConn]):
    """Protocol for getting connections."""
    def connection(self) -> ContextManager[TConn] | AsyncContextManager[TConn]: ...

class BaseRepository(Generic[TConn, TPool]):
    """Base repository with connection-agnostic logic."""

    def __init__(self, pool: TPool):
        self._pool = pool

    # Subclasses implement the actual I/O
```

### Implementation Example

```python
# commandbus/repositories/_base.py
from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Any

TConn = TypeVar("TConn")
TResult = TypeVar("TResult")

class BaseCommandRepository(ABC, Generic[TConn]):
    """Abstract base with shared logic, abstract I/O methods."""

    SAVE_SQL = "INSERT INTO commandbus.command ..."
    GET_SQL = "SELECT ... FROM commandbus.command WHERE ..."

    def build_save_params(self, metadata: CommandMetadata, queue_name: str) -> tuple:
        return (metadata.domain, ...)

    def parse_row(self, row: tuple) -> CommandMetadata:
        return CommandMetadata(...)

    @abstractmethod
    def execute(self, conn: TConn, sql: str, params: tuple) -> None:
        """Execute SQL - implemented by sync/async subclass."""
        ...

    @abstractmethod
    def fetch_one(self, conn: TConn, sql: str, params: tuple) -> tuple | None:
        """Fetch single row - implemented by sync/async subclass."""
        ...

    @abstractmethod
    def get_connection(self, provided: TConn | None = None):
        """Get connection context manager."""
        ...

    def save(self, metadata: CommandMetadata, queue_name: str, conn: TConn | None = None):
        """Save command - uses abstract methods for I/O."""
        params = self.build_save_params(metadata, queue_name)
        with self.get_connection(conn) as c:
            self.execute(c, self.SAVE_SQL, params)


# commandbus/repositories/command.py
class PostgresCommandRepository(BaseCommandRepository[AsyncConnection]):
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def execute(self, conn, sql, params):
        await conn.execute(sql, params)

    async def fetch_one(self, conn, sql, params):
        async with conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()

    @asynccontextmanager
    async def get_connection(self, provided=None):
        if provided:
            yield provided
        else:
            async with self._pool.connection() as conn:
                yield conn


# commandbus/sync/repositories/command.py
class SyncCommandRepository(BaseCommandRepository[Connection]):
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def execute(self, conn, sql, params):
        conn.execute(sql, params)

    def fetch_one(self, conn, sql, params):
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    @contextmanager
    def get_connection(self, provided=None):
        if provided:
            yield provided
        else:
            with self._pool.connection() as conn:
                yield conn
```

### Pros

- **High code reuse**: Business logic in base class (~70-80% shared)
- **Enforced consistency**: Both variants must implement same interface
- **Single source of truth**: SQL and parsing in one place
- **Extensible**: Easy to add new methods to base

### Cons

- **Complex typing**: Generic + Protocol + ABC is hard to follow
- **Async/sync method signatures differ**: Can't truly unify `async def` vs `def`
- **IDE confusion**: Type inference may struggle with generics
- **Testing complexity**: Need to test both implementations

### Duplication Reduction

| Component | Original | With Option B | Reduction |
|-----------|----------|---------------|-----------|
| Repositories | 100% | ~25% | **75%** |
| PGMQ Client | 100% | ~25% | **75%** |
| Worker | 100% | ~85% | 15% |
| Router | 100% | ~85% | 15% |
| **Total** | 3,130 | ~1,500 | **~52%** |

---

## Option C: Code Generation from Templates

### Concept

Write templates (Jinja2 or similar) that generate both sync and async code from a single source.

```
templates/
├── repository.py.j2
├── pgmq_client.py.j2
└── worker.py.j2

generate.py  # Script to render templates

Generated output:
src/commandbus/repositories/command.py      # async
src/commandbus/sync/repositories/command.py # sync
```

### Template Example

```jinja2
{# templates/repository.py.j2 #}
{% if async_mode %}
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
{% else %}
from psycopg import Connection
from psycopg_pool import ConnectionPool
{% endif %}

class {% if async_mode %}Postgres{% else %}Sync{% endif %}CommandRepository:
    def __init__(self, pool: {% if async_mode %}AsyncConnectionPool{% else %}ConnectionPool{% endif %}):
        self._pool = pool

    {% if async_mode %}async {% endif %}def save(
        self,
        metadata: CommandMetadata,
        queue_name: str,
        conn: {% if async_mode %}AsyncConnection{% else %}Connection{% endif %} | None = None,
    ) -> None:
        sql = """INSERT INTO commandbus.command ..."""
        params = (metadata.domain, ...)

        if conn is not None:
            {% if async_mode %}await {% endif %}conn.execute(sql, params)
        else:
            {% if async_mode %}async {% endif %}with self._pool.connection() as c:
                {% if async_mode %}await {% endif %}c.execute(sql, params)
```

### Pros

- **Zero runtime duplication**: Generated files are standalone
- **Single source of truth**: Template is the canonical version
- **Full flexibility**: Can handle any async/sync differences
- **No runtime overhead**: No abstraction layers

### Cons

- **Build complexity**: Need generation step in CI/dev workflow
- **Debugging harder**: Generated code may differ from template
- **IDE support**: Templates don't get syntax highlighting/completion
- **Merge conflicts**: Generated files in git can conflict
- **Learning curve**: Team must understand template system

### Duplication Reduction

| Component | Original | With Option C | Reduction |
|-----------|----------|---------------|-----------|
| All components | 100% | 0% (templates) | **100%** |
| **BUT** generated code | - | 100% (duplicated) | 0% |
| **Net** (templates only) | 3,130 | ~1,600 templates | **~49%** |

---

## Option D: Sync-First with Async Wrappers (Inversion)

### Concept

Flip the current approach: implement everything as **sync-first**, then wrap with `asyncio.to_thread()` for async callers.

```python
# Native sync implementation
class SyncCommandBus:
    def send(self, ...) -> SendResult:
        with self._pool.connection() as conn:
            # ... sync implementation

# Async wrapper (thin)
class CommandBus:
    def __init__(self, pool: AsyncConnectionPool):
        # Create sync pool from async pool settings
        self._sync_bus = SyncCommandBus(create_sync_pool(pool))

    async def send(self, ...) -> SendResult:
        return await asyncio.to_thread(self._sync_bus.send, ...)
```

### Pros

- **Sync is native**: No wrapper overhead for sync users
- **Minimal async code**: Just `to_thread` wrappers
- **Simple mental model**: Sync is "real", async is convenience

### Cons

- **Async performance regression**: `to_thread` has overhead
- **Pool duplication**: Need separate sync and async pools
- **Against Python ecosystem**: Most libraries are async-first
- **Worker complexity remains**: Still need thread-based concurrency
- **Breaking change**: Existing async users would see behavior change

### Duplication Reduction

| Component | Original | With Option D | Reduction |
|-----------|----------|---------------|-----------|
| Repositories | 100% | ~15% wrappers | **85%** |
| PGMQ Client | 100% | ~15% wrappers | **85%** |
| Worker | 100% | ~80% (still complex) | 20% |
| Router | 100% | ~80% | 20% |
| **Total** | 3,130 | ~1,200 | **~62%** |

---

## Option E: Hybrid Approach (Recommended)

### Concept

Combine the best elements:
1. **Shared SQL/Logic Core** (Option A) for repositories and PGMQ
2. **Separate Worker/Router** implementations (accept duplication where it matters)
3. **Shared Models and Policies** (already the case)

```
src/commandbus/
├── _core/                      # Shared logic (NEW)
│   ├── sql.py                  # SQL constants
│   ├── command_logic.py        # Parameter builders, parsers
│   ├── pgmq_logic.py           # PGMQ SQL and message parsing
│   └── process_logic.py        # Process state machines
│
├── repositories/               # Async implementations
│   ├── command.py              # Uses _core, adds async I/O
│   ├── audit.py
│   └── batch.py
│
├── pgmq/
│   └── client.py               # Async PGMQ, uses _core
│
├── worker.py                   # Async worker (full implementation)
├── bus.py                      # Async bus
│
└── sync/                       # Sync implementations
    ├── repositories/
    │   ├── command.py          # Uses _core, adds sync I/O
    │   ├── audit.py
    │   └── batch.py
    ├── pgmq.py                 # Sync PGMQ, uses _core
    ├── worker.py               # Sync worker (SEPARATE - accept duplication)
    ├── bus.py                  # Sync bus
    └── process/
        └── router.py           # Sync router (SEPARATE)
```

### Why Accept Worker/Router Duplication?

The Worker and Router complexity is in **concurrency patterns**, not SQL:

| Async Worker | Sync Worker |
|--------------|-------------|
| `asyncio.Semaphore` | `threading.Semaphore` |
| `asyncio.Event` | `threading.Event` |
| `asyncio.Task` | `Future` |
| `asyncio.gather` | `concurrent.futures.wait` |
| `asyncio.create_task` | `executor.submit` |
| `await conn.notifies()` | `select.select()` or polling |

These are **fundamentally different paradigms** - trying to abstract them adds complexity without reducing duplication.

### Implementation Structure

```python
# commandbus/_core/command_sql.py
"""Shared SQL and logic for command operations."""

class CommandSQL:
    """SQL constants for command operations."""

    SAVE = """
        INSERT INTO commandbus.command (...)
        VALUES (%s, %s, ...)
    """

    GET = """SELECT ... FROM commandbus.command WHERE ..."""

    UPDATE_STATUS = """UPDATE commandbus.command SET status = %s ..."""

    # Stored procedures
    SP_RECEIVE = "SELECT * FROM commandbus.sp_receive_command(%s, %s, %s)"
    SP_FINISH = "SELECT * FROM commandbus.sp_finish_command(%s, %s, %s, %s, %s)"


class CommandParams:
    """Parameter builders for command SQL."""

    @staticmethod
    def save(metadata: CommandMetadata, queue_name: str) -> tuple:
        return (
            metadata.domain,
            queue_name,
            metadata.msg_id,
            # ...
        )

    @staticmethod
    def get(domain: str, command_id: UUID) -> tuple:
        return (domain, command_id)


class CommandParsers:
    """Result parsers for command queries."""

    @staticmethod
    def from_row(row: tuple) -> CommandMetadata:
        return CommandMetadata(
            domain=row[0],
            queue_name=row[1],
            # ...
        )

    @staticmethod
    def from_sp_receive(row: tuple) -> tuple[CommandMetadata, int]:
        # Parse stored procedure result
        ...


# commandbus/repositories/command.py (async)
from commandbus._core.command_sql import CommandSQL, CommandParams, CommandParsers

class PostgresCommandRepository:
    def __init__(self, pool: AsyncConnectionPool):
        self._pool = pool

    async def save(self, metadata: CommandMetadata, queue_name: str, conn=None):
        params = CommandParams.save(metadata, queue_name)
        if conn:
            await conn.execute(CommandSQL.SAVE, params)
        else:
            async with self._pool.connection() as c:
                await c.execute(CommandSQL.SAVE, params)

    async def get(self, domain: str, command_id: UUID, conn=None) -> CommandMetadata | None:
        params = CommandParams.get(domain, command_id)
        # ... execute and parse with CommandParsers.from_row()


# commandbus/sync/repositories/command.py (sync)
from commandbus._core.command_sql import CommandSQL, CommandParams, CommandParsers

class SyncCommandRepository:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def save(self, metadata: CommandMetadata, queue_name: str, conn=None):
        params = CommandParams.save(metadata, queue_name)
        if conn:
            conn.execute(CommandSQL.SAVE, params)
        else:
            with self._pool.connection() as c:
                c.execute(CommandSQL.SAVE, params)

    def get(self, domain: str, command_id: UUID, conn=None) -> CommandMetadata | None:
        params = CommandParams.get(domain, command_id)
        # ... execute and parse with CommandParsers.from_row()
```

### Duplication Analysis

| Component | Lines | Shared Core | Async Impl | Sync Impl | Total New | Dup % |
|-----------|-------|-------------|------------|-----------|-----------|-------|
| CommandRepository | 950 | 300 | 200 | 200 | 700 | 21% |
| AuditLogger | 150 | 50 | 50 | 50 | 150 | 0% |
| BatchRepository | 350 | 120 | 80 | 80 | 280 | 20% |
| ProcessRepository | 400 | 150 | 100 | 100 | 350 | 12% |
| PgmqClient | 350 | 100 | 80 | 80 | 260 | 26% |
| CommandBus | 350 | 50 | 100 | 100 | 250 | 29% |
| **Worker** | 800 | 50 | 400 | 400 | 850 | **94%** |
| **Router** | 280 | 20 | 140 | 140 | 300 | **93%** |
| **Total** | 3,630 | 840 | 1,150 | 1,150 | 3,140 | **~30%** |

### Pros

- **Pragmatic**: Accepts duplication where it's unavoidable
- **Clear separation**: Core logic vs I/O adapters
- **Maintainable**: SQL changes in one place
- **Type-safe**: No complex generics
- **Testable**: Core logic unit-testable
- **Worker quality**: Each worker optimized for its paradigm

### Cons

- **Worker duplication**: ~800 lines duplicated for Worker + Router
- **More files**: Core + async + sync structure
- **Discipline required**: Must remember to update both impls for logic changes

---

## Comparison Matrix

| Criterion | Option A | Option B | Option C | Option D | Option E |
|-----------|----------|----------|----------|----------|----------|
| Code Reduction | 42% | 52% | 49%* | 62% | 30% |
| Complexity | Low | High | Medium | Medium | Low |
| Type Safety | High | Medium | High | High | High |
| IDE Support | Good | Poor | Poor | Good | Good |
| Build Process | Simple | Simple | Complex | Simple | Simple |
| Worker Quality | Poor | Poor | Good | Poor | **Best** |
| Migration Effort | Medium | High | High | Very High | Medium |
| Maintenance | Easy | Hard | Medium | Medium | Easy |

*Option C: Templates reduce source duplication but generated code is 100% duplicated

---

## Recommendation

**Option E (Hybrid)** is recommended because:

1. **Repositories benefit most from sharing** - SQL and parsing are identical
2. **Worker/Router are fundamentally different** - Async and sync concurrency patterns don't abstract well
3. **Pragmatic trade-off** - Accept ~800 lines of duplication to get clean, optimized implementations
4. **Maintainability** - Team can understand and modify each component independently
5. **Testing** - Core logic testable without I/O; both impls testable independently

### Migration Path

1. **Phase 1**: Create `_core/` with SQL constants and parsers (extract from existing)
2. **Phase 2**: Refactor async repositories to use `_core/`
3. **Phase 3**: Create sync repositories using same `_core/`
4. **Phase 4**: Implement sync Worker (separate, optimized for threads)
5. **Phase 5**: Implement sync Router (separate, optimized for threads)
6. **Phase 6**: Integration testing and cleanup

### Estimated Effort

| Phase | Files | Lines Changed | Days |
|-------|-------|---------------|------|
| Phase 1 | 5 new | ~500 extract | 2 |
| Phase 2 | 5 modify | ~200 refactor | 1 |
| Phase 3 | 5 new | ~500 new | 2 |
| Phase 4 | 1 new | ~400 new | 3 |
| Phase 5 | 1 new | ~150 new | 1 |
| Phase 6 | tests | ~300 new | 2 |
| **Total** | 17 files | ~2,050 lines | **11 days** |
