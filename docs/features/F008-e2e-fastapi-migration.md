# F008 - E2E Demo API: Flask to FastAPI Migration

## Summary

Replace Flask with FastAPI for the E2E demo application API layer to leverage native async/await support, automatic OpenAPI documentation, and better alignment with the async nature of commandbus.

## Prerequisites

- **[F007 - Handler DI & Transactions](F007-handler-dependency-injection.md)** must be implemented first
  - This migration will use `@handler` decorator for class-based handlers
  - Worker will use `register_instance()` for handler discovery
  - Handlers will use `ctx.conn` for transaction participation
  - Composition root pattern for dependency wiring

## Motivation

The current E2E demo application uses Flask with a `run_async()` helper to bridge sync Flask with async commandbus operations. This approach has limitations:

1. **Async/Sync Impedance Mismatch** - Flask is synchronous by design, requiring `run_async()` wrappers for every database operation
2. **Event Loop Management** - Manual event loop handling is error-prone and can lead to subtle bugs
3. **No Native Async** - Flask's WSGI foundation doesn't support true async request handling
4. **Connection Pool Lifecycle** - Awkward pool management with `atexit` handlers

FastAPI solves these issues:

1. **Native Async** - Built on ASGI with first-class async/await support
2. **Automatic OpenAPI** - Interactive API documentation out of the box
3. **Dependency Injection** - Clean pattern for database pool and other resources
4. **Type Safety** - Pydantic models for request/response validation
5. **Better Performance** - True async I/O without thread pool overhead

## Architecture

```
tests/e2e/
├── app/
│   ├── __init__.py           # Package init
│   ├── main.py               # FastAPI app factory + composition root (F007)
│   ├── config.py             # Configuration (unchanged)
│   ├── dependencies.py       # FastAPI dependency injection (pool, bus, tsq)
│   ├── handlers.py           # Handler classes with @handler decorator (F007)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py         # API router (refactored from Flask)
│   │   ├── commands.py       # Command endpoints
│   │   ├── stats.py          # Stats endpoints
│   │   ├── tsq.py            # TSQ endpoints
│   │   ├── audit.py          # Audit endpoints
│   │   └── schemas.py        # Pydantic models
│   └── web/
│       ├── __init__.py
│       └── routes.py         # HTML routes (Jinja2 templates)
├── run.py                    # Uvicorn entry point
└── ...
```

## Technical Design

### FastAPI Application Factory with Composition Root

The application factory uses the composition root pattern from F007 to wire all dependencies:

```python
# tests/e2e/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool

from commandbus import CommandBus, HandlerRegistry, Worker

from .config import Config
from .api.routes import api_router
from .web.routes import web_router
from .handlers import TestCommandHandlers


def create_registry(pool: AsyncConnectionPool) -> HandlerRegistry:
    """Composition root - wire all handler dependencies.

    Following F007 pattern: repositories -> services -> handlers.
    """
    # For E2E demo, handlers are simple - no service layer needed
    handlers = TestCommandHandlers()

    registry = HandlerRegistry()
    registry.register_instance(handlers)

    return registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown."""
    # Startup: Open connection pool
    pool = AsyncConnectionPool(
        conninfo=Config.DATABASE_URL,
        min_size=2,
        max_size=10,
        open=False,
    )
    await pool.open()

    # Create registry using composition root pattern (F007)
    registry = create_registry(pool)

    # Store in app state
    app.state.pool = pool
    app.state.registry = registry
    app.state.bus = CommandBus(pool)

    yield

    # Shutdown: Close pool
    await pool.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="CommandBus E2E Demo",
        description="Interactive demo and testing UI for commandbus library",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.include_router(api_router, prefix="/api/v1")
    app.include_router(web_router)

    return app
```

### Handler Classes with @handler Decorator

Using F007's `@handler` decorator for class-based handlers:

```python
# tests/e2e/app/handlers.py
import asyncio
from commandbus import Command, HandlerContext, handler
from commandbus.exceptions import PermanentCommandError, TransientCommandError


class TestCommandHandlers:
    """E2E test command handlers using @handler decorator (F007 pattern)."""

    @handler(domain="e2e", command_type="TestCommand")
    async def handle_test_command(self, cmd: Command, ctx: HandlerContext) -> dict:
        """Handle test commands with configurable behavior."""
        behavior = cmd.data.get("behavior", {})
        behavior_type = behavior.get("type", "success")
        execution_time_ms = behavior.get("execution_time_ms", 0)

        # Simulate execution time
        if execution_time_ms > 0:
            await asyncio.sleep(execution_time_ms / 1000)

        # Handle different behavior types
        if behavior_type == "success":
            return {"status": "completed", "payload": cmd.data.get("payload", {})}

        elif behavior_type == "fail_permanent":
            raise PermanentCommandError(
                code=behavior.get("error_code", "PERMANENT_ERROR"),
                message=behavior.get("error_message", "Permanent failure"),
            )

        elif behavior_type == "fail_transient":
            transient_failures = behavior.get("transient_failures", 1)
            if ctx.attempt <= transient_failures:
                raise TransientCommandError(
                    code=behavior.get("error_code", "TRANSIENT_ERROR"),
                    message=f"Transient failure (attempt {ctx.attempt})",
                )
            return {"status": "completed_after_retry", "attempts": ctx.attempt}

        else:
            raise PermanentCommandError(
                code="UNKNOWN_BEHAVIOR",
                message=f"Unknown behavior type: {behavior_type}",
            )
```

### Dependency Injection

```python
# tests/e2e/app/dependencies.py
from typing import Annotated
from fastapi import Depends, Request
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.ops.troubleshooting import TroubleshootingQueue


async def get_pool(request: Request) -> AsyncConnectionPool:
    """Get database pool from app state."""
    return request.app.state.pool


async def get_command_bus(
    pool: Annotated[AsyncConnectionPool, Depends(get_pool)]
) -> CommandBus:
    """Get CommandBus instance."""
    return CommandBus(pool)


async def get_tsq(
    pool: Annotated[AsyncConnectionPool, Depends(get_pool)]
) -> TroubleshootingQueue:
    """Get TroubleshootingQueue instance."""
    return TroubleshootingQueue(pool)


# Type aliases for cleaner route signatures
Pool = Annotated[AsyncConnectionPool, Depends(get_pool)]
Bus = Annotated[CommandBus, Depends(get_command_bus)]
TSQ = Annotated[TroubleshootingQueue, Depends(get_tsq)]
```

### Pydantic Schemas

```python
# tests/e2e/app/api/schemas.py
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CommandBehavior(BaseModel):
    """Test command behavior specification."""
    type: str = Field(
        default="success",
        description="Behavior type: success, fail_permanent, fail_transient, etc."
    )
    transient_failures: int = Field(default=0)
    execution_time_ms: int = Field(default=0)
    error_code: str | None = None
    error_message: str | None = None


class CreateCommandRequest(BaseModel):
    """Request to create a test command."""
    behavior: CommandBehavior = Field(default_factory=CommandBehavior)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)


class CreateCommandResponse(BaseModel):
    """Response after creating a command."""
    command_id: UUID
    status: str = "PENDING"
    behavior: CommandBehavior
    payload: dict[str, Any]
    message: str


class BulkCreateRequest(BaseModel):
    """Request to create multiple test commands."""
    count: int = Field(default=1, ge=1, le=10000)
    behavior: CommandBehavior | None = None
    behavior_distribution: dict[str, int] | None = None
    execution_time_ms: int = Field(default=0)
    max_attempts: int = Field(default=3)


class CommandResponse(BaseModel):
    """Single command details."""
    command_id: UUID
    domain: str
    command_type: str
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime | None
    updated_at: datetime | None
    correlation_id: UUID | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    payload: dict[str, Any] | None = None


class CommandListResponse(BaseModel):
    """Paginated list of commands."""
    commands: list[CommandResponse]
    total: int
    limit: int
    offset: int


class StatsOverviewResponse(BaseModel):
    """Dashboard overview statistics."""
    status_counts: dict[str, int]
    processing_rate: dict[str, float | int]
    recent_change: dict[str, int]
    error: str | None = None
```

### Refactored API Routes

```python
# tests/e2e/app/api/commands.py
from uuid import uuid4, UUID

from fastapi import APIRouter, HTTPException

from commandbus.bus import CommandBus

from ..dependencies import Pool, Bus
from .schemas import (
    CreateCommandRequest,
    CreateCommandResponse,
    BulkCreateRequest,
    CommandResponse,
    CommandListResponse,
)

router = APIRouter(prefix="/commands", tags=["Commands"])

E2E_DOMAIN = "e2e"


@router.post("", response_model=CreateCommandResponse, status_code=201)
async def create_command(
    request: CreateCommandRequest,
    bus: Bus,
):
    """Create a single test command."""
    command_id = uuid4()

    await bus.send(
        domain=E2E_DOMAIN,
        command_type="TestCommand",
        command_id=command_id,
        data={"behavior": request.behavior.model_dump(), "payload": request.payload},
        max_attempts=request.max_attempts,
    )

    return CreateCommandResponse(
        command_id=command_id,
        behavior=request.behavior,
        payload=request.payload,
        message="Command created and queued",
    )


@router.get("", response_model=CommandListResponse)
async def list_commands(
    pool: Pool,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    """Query commands with optional status filter."""
    limit = min(limit, 100)

    async with pool.connection() as conn, conn.cursor() as cur:
        query = """
            SELECT command_id, domain, command_type, status, attempts, max_attempts,
                   created_at, updated_at, last_error_code, last_error_msg, correlation_id
            FROM command_bus_command
            WHERE domain = %s
        """
        params = [E2E_DOMAIN]

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        await cur.execute(query, params)
        rows = await cur.fetchall()

        # Get total count
        count_query = "SELECT COUNT(*) FROM command_bus_command WHERE domain = %s"
        count_params = [E2E_DOMAIN]
        if status:
            count_query += " AND status = %s"
            count_params.append(status)
        await cur.execute(count_query, count_params)
        total_row = await cur.fetchone()
        total = total_row[0] if total_row else 0

    commands = [
        CommandResponse(
            command_id=row[0],
            domain=row[1],
            command_type=row[2],
            status=row[3],
            attempts=row[4],
            max_attempts=row[5],
            created_at=row[6],
            updated_at=row[7],
            last_error_code=row[8],
            last_error_message=row[9],
            correlation_id=row[10],
        )
        for row in rows
    ]

    return CommandListResponse(
        commands=commands,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{command_id}", response_model=CommandResponse)
async def get_command(command_id: UUID, bus: Bus):
    """Get single command details."""
    cmd = await bus.get_command(E2E_DOMAIN, command_id)

    if cmd is None:
        raise HTTPException(status_code=404, detail="Command not found")

    return CommandResponse(
        command_id=cmd.command_id,
        domain=cmd.domain,
        command_type=cmd.command_type,
        status=cmd.status.value,
        attempts=cmd.attempts,
        max_attempts=cmd.max_attempts,
        created_at=cmd.created_at,
        updated_at=cmd.updated_at,
        correlation_id=cmd.correlation_id,
        last_error_code=cmd.last_error_code,
        last_error_message=cmd.last_error_msg,
        payload=cmd.data,
    )
```

### Entry Point

```python
# tests/e2e/run.py
import uvicorn
from app.main import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "run:app",
        host="0.0.0.0",
        port=5001,
        reload=True,
    )
```

## Key Differences: Flask vs FastAPI

| Aspect | Flask (Before) | FastAPI (After) |
|--------|----------------|-----------------|
| Async support | `run_async()` helper | Native async/await |
| Pool lifecycle | `atexit` handler | `lifespan` context manager |
| Request validation | Manual | Pydantic automatic |
| API docs | None | Auto-generated OpenAPI |
| Type hints | Optional | Enforced via Pydantic |
| Error handling | Manual `try/except` | `HTTPException` + handlers |
| Dependency injection | Flask `g` or app config | FastAPI `Depends()` |

## User Stories

| Story | Description | Priority | F007 Dependency |
|-------|-------------|----------|-----------------|
| S031 | FastAPI Application Factory with Composition Root | Must Have | Yes - uses `create_registry()` pattern |
| S032 | Dependency Injection Setup | Must Have | Yes - registry in app state |
| S033 | Command Endpoints Migration | Must Have | No |
| S034 | Stats Endpoints Migration | Must Have | No |
| S035 | TSQ Endpoints Migration | Must Have | No |
| S036 | Audit Endpoints Migration | Should Have | No |
| S037 | Pydantic Schema Definitions | Must Have | No |
| S038 | Web Routes with Jinja2 | Should Have | No |
| S039 | OpenAPI Documentation Review | Could Have | No |
| S040 | Handler Classes with @handler Decorator | Must Have | Yes - uses F007 `@handler` |

**Note:** Stories S031, S032, and S040 leverage patterns from F007 (Handler DI & Transactions). F007 must be implemented first.

## Migration Strategy

### Phase 1: Parallel Development
1. Create FastAPI app alongside Flask
2. Implement all endpoints with Pydantic schemas
3. Test against same database

### Phase 2: Validation
1. Run both apps simultaneously
2. Compare responses for all endpoints
3. Verify template rendering works

### Phase 3: Cutover
1. Update `run.py` to use FastAPI
2. Update `Makefile` targets
3. Remove Flask code
4. Update dependencies in `pyproject.toml`

## Dependencies

### Add
```toml
[project.optional-dependencies]
e2e = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "jinja2>=3.1.4",
    "python-multipart>=0.0.9",  # For form data
]
```

### Remove
```toml
# No longer needed
# "flask>=3.1.0",
```

## Success Criteria

1. All existing API endpoints work identically
2. OpenAPI docs available at `/docs` and `/redoc`
3. Templates render correctly with Jinja2
4. No `run_async()` or event loop workarounds
5. Clean startup/shutdown via lifespan
6. All E2E tests pass

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Template incompatibility | Medium | Jinja2 works with both; minimal changes |
| Static file serving | Low | FastAPI `StaticFiles` mount |
| Session/flash messages | Medium | Not used in current app |
| Form handling | Low | `python-multipart` for form data |

## LLM Agent Notes

**Reference Files:**
- `tests/e2e/app/__init__.py` - Current Flask factory (to be replaced)
- `tests/e2e/app/api/routes.py` - Current API routes (to be refactored)
- `tests/e2e/app/web/routes.py` - Current web routes (to be adapted)
- `tests/e2e/run.py` - Entry point (to be updated)
- `src/commandbus/handler.py` - F007 HandlerRegistry, @handler decorator

**Patterns to Follow:**
- FastAPI `lifespan` for startup/shutdown
- `Depends()` for FastAPI dependency injection
- Pydantic `BaseModel` for all request/response schemas
- `APIRouter` for route organization
- **F007 Patterns:**
  - `@handler(domain, command_type)` decorator on handler methods
  - `register_instance()` for handler discovery
  - Composition root pattern in `create_registry()`
  - Stateless handler classes (no mutable instance state)

**Constraints:**
- Must maintain exact API compatibility for existing UI
- Templates must continue to work
- Database operations must use native async
- No new external dependencies beyond FastAPI ecosystem
- F007 must be implemented before starting F008

**Verification Steps:**
1. `make e2e-setup` - Database ready
2. `make e2e-app` - App starts
3. `curl http://localhost:5001/api/v1/health` - Returns OK
4. Open `http://localhost:5001/docs` - OpenAPI docs work
5. UI functionality unchanged
6. Handler discovery works via `register_instance()`
