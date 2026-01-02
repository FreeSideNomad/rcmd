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
from commandbus.exceptions import PermanentCommandError, TransientCommandError
from commandbus.handler import HandlerRegistry
from commandbus.models import Command, CommandStatus, HandlerContext
from commandbus.ops.troubleshooting import TroubleshootingQueue
from commandbus.worker import Worker

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from uuid import UUID

# Shared state for tracking transient failure attempts per command
_failure_counts: dict[str, int] = {}


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
            """Test command handler that simulates different behaviors.

            Supported behavior types:
            - success: Complete successfully
            - fail_permanent: Raise PermanentCommandError immediately
            - fail_transient: Raise TransientCommandError every time
            - fail_transient_then_succeed: Fail N times then succeed
            - timeout: Simulate long-running operation (use with short visibility_timeout)
            """
            # Get behavior from command data if present
            cmd_behavior = cmd.data.get("behavior", behavior)
            behavior_type = cmd_behavior.get("type", "success")
            execution_time_ms = cmd_behavior.get("execution_time_ms", 0)
            error_code = cmd_behavior.get("error_code", "TEST_ERROR")
            error_message = cmd_behavior.get("error_message", "Test error")
            transient_failures = cmd_behavior.get("transient_failures", 3)

            # Simulate execution time
            if execution_time_ms > 0:
                await asyncio.sleep(execution_time_ms / 1000)

            if behavior_type == "success":
                return {
                    "status": "success",
                    "processed_at": time.time(),
                    "data": cmd.data,
                }

            if behavior_type == "fail_permanent":
                raise PermanentCommandError(
                    code=error_code,
                    message=error_message,
                    details={"command_id": str(cmd.command_id)},
                )

            if behavior_type == "fail_transient":
                raise TransientCommandError(
                    code=error_code,
                    message=error_message,
                    details={"command_id": str(cmd.command_id)},
                )

            if behavior_type == "fail_transient_then_succeed":
                # Track failures per command
                cmd_key = str(cmd.command_id)
                current_count = _failure_counts.get(cmd_key, 0)
                _failure_counts[cmd_key] = current_count + 1

                if current_count < transient_failures:
                    raise TransientCommandError(
                        code=error_code,
                        message=f"Transient failure {current_count + 1}/{transient_failures}",
                        details={"attempt": current_count + 1},
                    )
                # Clean up and succeed
                del _failure_counts[cmd_key]
                return {
                    "status": "success",
                    "processed_at": time.time(),
                    "attempts_before_success": transient_failures,
                }

            if behavior_type == "timeout":
                # Sleep longer than visibility_timeout to simulate timeout
                timeout_ms = cmd_behavior.get("timeout_ms", 10000)
                await asyncio.sleep(timeout_ms / 1000)
                return {
                    "status": "success",
                    "processed_at": time.time(),
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


@pytest.fixture
def wait_for_tsq(
    wait_for_status: Callable[[UUID, CommandStatus, float], Any],
) -> Callable[[UUID, float], Any]:
    """Helper fixture to wait for command to move to TSQ."""

    async def _wait(command_id: UUID, timeout: float = 10.0) -> Any:
        return await wait_for_status(command_id, CommandStatus.IN_TROUBLESHOOTING_QUEUE, timeout)

    return _wait


@pytest.fixture
async def tsq(pool: AsyncConnectionPool) -> TroubleshootingQueue:
    """Create a TroubleshootingQueue for TSQ operations."""
    return TroubleshootingQueue(pool)


@pytest.fixture
def create_failure_worker(
    pool: AsyncConnectionPool,
    create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
) -> Callable[[int, int], Worker]:
    """Factory fixture for creating workers with specific retry settings."""

    def _create(max_attempts: int = 3, visibility_timeout: int = 30) -> Worker:
        registry = create_handler_registry({"type": "success"})
        return Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=visibility_timeout,
            concurrency=1,
            max_attempts=max_attempts,
        )

    return _create


@pytest.fixture
def reset_failure_counts() -> Callable[[], None]:
    """Reset the global failure counter between tests."""

    def _reset() -> None:
        _failure_counts.clear()

    return _reset
