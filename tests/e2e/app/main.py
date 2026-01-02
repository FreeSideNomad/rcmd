"""E2E Demo Application - FastAPI app factory with composition root."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from psycopg_pool import AsyncConnectionPool

from commandbus import CommandBus, HandlerRegistry

from .config import Config
from .handlers import TestCommandHandlers


def create_registry(pool: AsyncConnectionPool) -> HandlerRegistry:
    """Composition root - wire all handler dependencies.

    Following F007 pattern: repositories -> services -> handlers.
    For E2E demo, handlers are simple - no service layer needed.
    """
    handlers = TestCommandHandlers(pool)

    registry = HandlerRegistry()
    registry.register_instance(handlers)

    return registry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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

    # Store in app state for access via dependencies
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

    # Import routers here to avoid circular imports
    from .api.routes import api_router
    from .web.routes import web_router

    # Mount API router at /api/v1
    app.include_router(api_router, prefix="/api/v1")

    # Mount web router at root
    app.include_router(web_router)

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
