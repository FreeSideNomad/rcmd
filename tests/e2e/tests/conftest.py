"""E2E test fixtures and utilities."""

from __future__ import annotations

import asyncio
import contextlib
import os
import time
from typing import TYPE_CHECKING, Any

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.handler import HandlerRegistry
from commandbus.models import Command, CommandStatus, HandlerContext
from commandbus.worker import Worker

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from uuid import UUID


@pytest.fixture
def database_url() -> str:
    """Get database URL from environment."""
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/commandbus",  # pragma: allowlist secret
    )


@pytest.fixture
async def pool(database_url: str) -> AsyncGenerator[AsyncConnectionPool, None]:
    """Create a connection pool for testing."""
    async with AsyncConnectionPool(
        conninfo=database_url, min_size=1, max_size=10, open=False
    ) as pool:
        yield pool


@pytest.fixture
async def command_bus(pool: AsyncConnectionPool) -> CommandBus:
    """Create a CommandBus with real database connection."""
    return CommandBus(pool)


@pytest.fixture
async def cleanup_db(pool: AsyncConnectionPool) -> AsyncGenerator[None, None]:
    """Clean up test data before and after each test."""
    # Cleanup before test
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM command_bus_audit")
        await conn.execute("DELETE FROM command_bus_command")
        # Clean up PGMQ queues
        await conn.execute("DELETE FROM pgmq.q_e2e__commands")
    yield
    # Cleanup after test
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM command_bus_audit")
        await conn.execute("DELETE FROM command_bus_command")
        await conn.execute("DELETE FROM pgmq.q_e2e__commands")


@pytest.fixture
def create_handler_registry() -> Callable[[dict[str, Any] | None], HandlerRegistry]:
    """Factory fixture for creating handler registries with custom behavior."""

    def _create(behavior: dict[str, Any] | None = None) -> HandlerRegistry:
        registry = HandlerRegistry()
        behavior = behavior or {"type": "success"}

        async def test_handler(cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
            """Test command handler that simulates different behaviors."""
            # Get behavior from command data if present
            cmd_behavior = cmd.data.get("behavior", behavior)
            behavior_type = cmd_behavior.get("type", "success")
            execution_time_ms = cmd_behavior.get("execution_time_ms", 0)

            # Simulate execution time
            if execution_time_ms > 0:
                await asyncio.sleep(execution_time_ms / 1000)

            if behavior_type == "success":
                return {
                    "status": "success",
                    "processed_at": time.time(),
                    "data": cmd.data,
                }

            raise ValueError(f"Unknown behavior type: {behavior_type}")

        registry.register("e2e", "TestCommand", test_handler)
        return registry

    return _create


@pytest.fixture
async def worker(
    pool: AsyncConnectionPool,
    create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
) -> Worker:
    """Create a Worker with test handler registry."""
    registry = create_handler_registry({"type": "success"})
    return Worker(
        pool,
        domain="e2e",
        registry=registry,
        visibility_timeout=30,
        concurrency=2,
    )


@pytest.fixture
async def worker_task(worker: Worker) -> AsyncGenerator[asyncio.Task[None], None]:
    """Start a worker and yield the task."""
    task = asyncio.create_task(worker.run())
    # Give worker time to start
    await asyncio.sleep(0.1)
    yield task
    worker.stop()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.fixture
def wait_for_status(
    command_bus: CommandBus,
) -> Callable[[UUID, CommandStatus, float], Any]:
    """Helper fixture to wait for command to reach a specific status."""

    async def _wait(
        command_id: UUID,
        target_status: CommandStatus,
        timeout: float = 10.0,
    ) -> Any:
        deadline = time.time() + timeout
        while time.time() < deadline:
            cmd = await command_bus.get_command("e2e", command_id)
            if cmd and cmd.status == target_status:
                return cmd
            await asyncio.sleep(0.1)
        raise TimeoutError(
            f"Command {command_id} did not reach status {target_status} within {timeout}s"
        )

    return _wait


@pytest.fixture
def wait_for_completion(
    wait_for_status: Callable[[UUID, CommandStatus, float], Any],
) -> Callable[[UUID, float], Any]:
    """Helper fixture to wait for command completion."""

    async def _wait(command_id: UUID, timeout: float = 10.0) -> Any:
        return await wait_for_status(command_id, CommandStatus.COMPLETED, timeout)

    return _wait
