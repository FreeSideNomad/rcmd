"""E2E Worker with @handler decorator pattern (F007)."""

import asyncio
import logging

from psycopg_pool import AsyncConnectionPool

from commandbus import CommandBus, HandlerRegistry, RetryPolicy, Worker
from commandbus.process import PostgresProcessRepository, ProcessReplyRouter

from .config import Config, ConfigStore, RetryConfig
from .handlers import NoOpHandlers, ReportingHandlers, TestCommandHandlers
from .process.statement_report import StatementReportProcess

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
    # Create handler instances with dependencies
    test_handlers = TestCommandHandlers(pool)
    no_op_handlers = NoOpHandlers(pool)
    reporting_handlers = ReportingHandlers(pool)

    # Register all decorated handlers
    registry = HandlerRegistry()
    registry.register_instance(test_handlers)
    registry.register_instance(no_op_handlers)
    registry.register_instance(reporting_handlers)

    return registry


def create_worker(
    pool: AsyncConnectionPool,
    domain: str = "e2e",
    retry_config: RetryConfig | None = None,
    visibility_timeout: int = 30,
    registry: HandlerRegistry | None = None,
) -> Worker:
    """Create a worker for a specific domain with configurable settings."""
    if retry_config is None:
        retry_config = RetryConfig()

    if registry is None:
        registry = create_registry(pool)

    retry_policy = RetryPolicy(
        max_attempts=retry_config.max_attempts,
        backoff_schedule=retry_config.backoff_schedule,
    )

    return Worker(
        pool=pool,
        domain=domain,
        registry=registry,
        retry_policy=retry_policy,
        visibility_timeout=visibility_timeout,
    )


async def run_worker() -> None:
    """Run workers and reply router with configuration from database."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    pool = await create_pool()
    registry = create_registry(pool)
    bus = CommandBus(pool)
    process_repo = PostgresProcessRepository(pool)

    # Process Managers
    report_process = StatementReportProcess(
        command_bus=bus,
        process_repo=process_repo,
        reply_queue="reporting__process_replies",
        pool=pool,
    )
    managers = {report_process.process_type: report_process}

    try:
        config_store = await get_config_store(pool)

        # Workers
        e2e_worker = create_worker(
            pool,
            domain="e2e",
            retry_config=config_store.retry,
            visibility_timeout=config_store.worker.visibility_timeout,
            registry=registry,
        )

        reporting_worker = create_worker(
            pool,
            domain="reporting",
            retry_config=config_store.retry,
            visibility_timeout=config_store.worker.visibility_timeout,
            registry=registry,
        )

        # Router
        router = ProcessReplyRouter(
            pool=pool,
            process_repo=process_repo,
            managers=managers,
            reply_queue="reporting__process_replies",
            domain="reporting",
        )

        logger.info(
            "Starting E2E workers and router with concurrency=%d, "
            "visibility_timeout=%ds, poll_interval=%.1fs",
            config_store.worker.concurrency,
            config_store.worker.visibility_timeout,
            config_store.worker.poll_interval,
        )

        # Run everything concurrently
        await asyncio.gather(
            e2e_worker.run(
                concurrency=config_store.worker.concurrency,
                poll_interval=config_store.worker.poll_interval,
            ),
            reporting_worker.run(
                concurrency=config_store.worker.concurrency,
                poll_interval=config_store.worker.poll_interval,
            ),
            router.run(
                concurrency=config_store.worker.concurrency,
                poll_interval=config_store.worker.poll_interval,
            ),
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(run_worker())
