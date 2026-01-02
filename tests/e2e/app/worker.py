"""E2E Worker with @handler decorator pattern (F007)."""

import asyncio
import logging

from psycopg_pool import AsyncConnectionPool

from commandbus import HandlerRegistry, RetryPolicy, Worker

from .config import Config, ConfigStore, RetryConfig, WorkerConfig
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


async def create_worker(
    pool: AsyncConnectionPool,
    config: WorkerConfig | None = None,
    retry_config: RetryConfig | None = None,
) -> Worker:
    """Create a worker with configurable settings."""
    if config is None:
        config = WorkerConfig()
    if retry_config is None:
        retry_config = RetryConfig()

    registry = create_registry(pool)

    retry_policy = RetryPolicy(
        max_attempts=retry_config.max_attempts,
        base_delay_ms=retry_config.base_delay_ms,
        max_delay_ms=retry_config.max_delay_ms,
        multiplier=retry_config.backoff_multiplier,
    )

    return Worker(
        pool=pool,
        domain="e2e",
        handler_registry=registry,
        retry_policy=retry_policy,
        concurrency=config.concurrency,
        visibility_timeout=config.visibility_timeout,
        poll_interval=config.poll_interval,
        batch_size=config.batch_size,
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
        worker = await create_worker(
            pool,
            config=config_store.worker,
            retry_config=config_store.retry,
        )

        logger.info(
            "Starting E2E worker with concurrency=%d, visibility_timeout=%ds",
            config_store.worker.concurrency,
            config_store.worker.visibility_timeout,
        )

        await worker.run()
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run_worker())
