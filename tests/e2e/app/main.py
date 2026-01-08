"""E2E Demo Application - FastAPI app factory with composition root."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from psycopg_pool import AsyncConnectionPool

from commandbus.pgmq import PgmqClient

from .config import Config, ConfigStore
from .handlers import create_registry
from .models import TestCommandRepository
from .runtime import RuntimeManager


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

    # Store shared objects in app state for access via dependencies
    app.state.pool = pool
    app.state.registry = registry

    # Ensure reporting queues exist
    pgmq = PgmqClient(pool)
    await pgmq.create_queue("reporting__commands")
    await pgmq.create_queue("reporting__process_replies")

    # Configuration & runtime manager setup
    config_store = ConfigStore()
    await config_store.load_from_db(pool)
    behavior_repo = TestCommandRepository(pool)
    runtime_manager = RuntimeManager(pool=pool, behavior_repo=behavior_repo)
    await runtime_manager.start(config_store.runtime)
    app.state.runtime_manager = runtime_manager

    yield

    # Shutdown resources
    await runtime_manager.shutdown()
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
