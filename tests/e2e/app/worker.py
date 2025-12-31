"""E2E Worker with behavior-based test command handler."""

import asyncio
import logging
from typing import Any

from psycopg_pool import AsyncConnectionPool

from commandbus import (
    Command,
    HandlerContext,
    HandlerRegistry,
    PermanentCommandError,
    RetryPolicy,
    TransientCommandError,
    Worker,
)

from .config import Config, ConfigStore, RetryConfig, WorkerConfig
from .models import TestCommandRepository

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
    """Create handler registry with test command handler."""
    registry = HandlerRegistry()

    @registry.handler("e2e", "TestCommand")
    async def handle_test_command(cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle test command based on behavior specification."""
        repo = TestCommandRepository(pool)

        # Increment attempt count
        attempt = await repo.increment_attempts(cmd.command_id)

        # Get behavior from test_command table
        test_cmd = await repo.get_by_command_id(cmd.command_id)
        if not test_cmd:
            raise PermanentCommandError(
                code="TEST_COMMAND_NOT_FOUND",
                message=f"Test command {cmd.command_id} not found in test_command table",
            )

        behavior = test_cmd.behavior
        behavior_type = behavior.get("type", "success")

        # Simulate execution time (applies to all behaviors)
        execution_time_ms = behavior.get("execution_time_ms", 0)
        if execution_time_ms > 0:
            await asyncio.sleep(execution_time_ms / 1000)

        # Execute based on behavior type
        match behavior_type:
            case "success":
                result = {"status": "success", "attempt": attempt}
                await repo.mark_processed(cmd.command_id, result)
                return result

            case "fail_permanent":
                error_code = behavior.get("error_code", "PERMANENT_ERROR")
                error_message = behavior.get("error_message", "Simulated permanent failure")
                raise PermanentCommandError(code=error_code, message=error_message)

            case "fail_transient":
                error_code = behavior.get("error_code", "TRANSIENT_ERROR")
                error_message = behavior.get("error_message", "Simulated transient failure")
                raise TransientCommandError(code=error_code, message=error_message)

            case "fail_transient_then_succeed":
                transient_failures = behavior.get("transient_failures", 1)
                if attempt <= transient_failures:
                    raise TransientCommandError(
                        code="TRANSIENT",
                        message=f"Transient failure {attempt}/{transient_failures}",
                    )
                result = {"status": "success", "attempts": attempt}
                await repo.mark_processed(cmd.command_id, result)
                return result

            case "timeout":
                # For timeout behavior, execution_time_ms should be > visibility_timeout
                # The handler will sleep and the message will time out and be redelivered
                # Eventually it will succeed after the configured execution time
                result = {"status": "success", "attempt": attempt, "simulated_timeout": True}
                await repo.mark_processed(cmd.command_id, result)
                return result

            case _:
                raise PermanentCommandError(
                    code="UNKNOWN_BEHAVIOR",
                    message=f"Unknown behavior type: {behavior_type}",
                )

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
