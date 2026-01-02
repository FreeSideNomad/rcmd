"""E2E Worker with @handler decorator pattern (F007)."""

import asyncio
import logging

from psycopg_pool import AsyncConnectionPool

from commandbus import HandlerRegistry, RetryPolicy, Worker

from .config import Config, ConfigStore, RetryConfig
from .handlers import TestCommandHandlers

logger = logging.getLogger(__name__)


async def create_pool() -> AsyncConnectionPool:
    """Create database connection pool."""
    pool = AsyncConnectionPool(
        conninfo=Config.DATABASE_URL,
        min_size=2,
        max_size=10,
    )
    await pool.open()
    return pool


async def get_config_store(pool: AsyncConnectionPool) -> ConfigStore:
    """Get configuration store loaded from database."""
    store = ConfigStore()
    await store.load_from_db(pool)
    return store


def create_registry(pool: AsyncConnectionPool) -> HandlerRegistry:
    """Create handler registry using F007 composition root pattern.

    This uses:
    - @handler decorator on class methods
    - register_instance() for automatic handler discovery
    """
    # Create handler instance with dependencies
    handlers = TestCommandHandlers(pool)

    # Register all decorated handlers
    registry = HandlerRegistry()
    registry.register_instance(handlers)

    return registry


def create_worker(
    pool: AsyncConnectionPool,
    retry_config: RetryConfig | None = None,
    visibility_timeout: int = 30,
) -> Worker:
    """Create a worker with configurable settings.

    Note: concurrency and poll_interval are passed to worker.run(),
    not to the constructor.
    """
    if retry_config is None:
        retry_config = RetryConfig()

    registry = create_registry(pool)

    retry_policy = RetryPolicy(
        max_attempts=retry_config.max_attempts,
        backoff_schedule=retry_config.backoff_schedule,
    )

    return Worker(
        pool=pool,
        domain="e2e",
        registry=registry,
        retry_policy=retry_policy,
        visibility_timeout=visibility_timeout,
    )


async def run_worker() -> None:
    """Run the worker with configuration from database."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    pool = await create_pool()

    try:
        config_store = await get_config_store(pool)
        worker = create_worker(
            pool,
            retry_config=config_store.retry,
            visibility_timeout=config_store.worker.visibility_timeout,
        )

        logger.info(
            "Starting E2E worker with concurrency=%d, visibility_timeout=%ds, poll_interval=%.1fs",
            config_store.worker.concurrency,
            config_store.worker.visibility_timeout,
            config_store.worker.poll_interval,
        )

        await worker.run(
            concurrency=config_store.worker.concurrency,
            poll_interval=config_store.worker.poll_interval,
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run_worker())
