"""E2E test fixtures and utilities."""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import time
from typing import TYPE_CHECKING, Any

import pytest
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.exceptions import PermanentCommandError, TransientCommandError
from commandbus.handler import HandlerRegistry
from commandbus.models import Command, CommandStatus, HandlerContext
from commandbus.ops.troubleshooting import TroubleshootingQueue
from commandbus.pgmq.client import PgmqClient
from commandbus.policies import RetryPolicy
from commandbus.worker import Worker
from tests.e2e.app.models import BatchSummary, BatchSummaryRepository

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from uuid import UUID

# Shared state for tracking transient failure attempts per command
_failure_counts: dict[str, int] = {}

# Default visibility timeout for timeout simulation
DEFAULT_VISIBILITY_TIMEOUT_SECONDS = 30


def _sample_duration(min_ms: int, max_ms: int) -> float:
    """Sample duration from normal distribution, clamped to [min, max]."""
    if min_ms == max_ms:
        return float(min_ms)
    if min_ms > max_ms:
        min_ms, max_ms = max_ms, min_ms
    mean = (min_ms + max_ms) / 2
    std_dev = (max_ms - min_ms) / 6
    sample = random.gauss(mean, std_dev)
    return max(min_ms, min(max_ms, sample))


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
        await conn.execute("DELETE FROM commandbus.audit")
        await conn.execute("DELETE FROM commandbus.command")
        # Clean up PGMQ queues
        await conn.execute("DELETE FROM pgmq.q_e2e__commands")
    yield
    # Cleanup after test
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM commandbus.audit")
        await conn.execute("DELETE FROM commandbus.command")
        await conn.execute("DELETE FROM pgmq.q_e2e__commands")


@pytest.fixture
def create_handler_registry() -> Callable[[dict[str, Any] | None], HandlerRegistry]:
    """Factory fixture for creating handler registries with custom behavior."""

    def _create(behavior: dict[str, Any] | None = None) -> HandlerRegistry:
        registry = HandlerRegistry()
        behavior = behavior or {}

        async def test_handler(cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
            """Test command handler using probabilistic behavior evaluation.

            Probabilistic behavior evaluation (evaluated sequentially):
            - fail_permanent_pct: Chance of permanent failure (0-100%)
            - fail_transient_pct: Chance of transient failure (0-100%)
            - timeout_pct: Chance of timeout behavior (0-100%)
            - If none trigger, command succeeds with duration from normal distribution

            For deterministic failures in tests, use 100% probability.
            """
            # Get behavior from command data if present
            cmd_behavior = cmd.data.get("behavior", behavior)
            error_code = cmd_behavior.get("error_code", "TEST_ERROR")
            error_message = cmd_behavior.get("error_message", "Test error")

            # Roll for permanent failure
            fail_permanent_pct = cmd_behavior.get("fail_permanent_pct", 0.0)
            if random.random() * 100 < fail_permanent_pct:
                raise PermanentCommandError(
                    code=error_code,
                    message=error_message,
                    details={"command_id": str(cmd.command_id)},
                )

            # Roll for transient failure
            fail_transient_pct = cmd_behavior.get("fail_transient_pct", 0.0)
            # Support for "fail N times then succeed" pattern using transient_failures count
            transient_failures = cmd_behavior.get("transient_failures", 0)
            if transient_failures > 0:
                # Track failures per command for deterministic fail-then-succeed
                cmd_key = str(cmd.command_id)
                current_count = _failure_counts.get(cmd_key, 0)
                if current_count < transient_failures:
                    _failure_counts[cmd_key] = current_count + 1
                    raise TransientCommandError(
                        code=error_code,
                        message=f"Transient failure {current_count + 1}/{transient_failures}",
                        details={"attempt": current_count + 1},
                    )
                # Clean up after succeeding
                _failure_counts.pop(cmd_key, None)
            elif random.random() * 100 < fail_transient_pct:
                raise TransientCommandError(
                    code=error_code,
                    message=error_message,
                    details={"command_id": str(cmd.command_id)},
                )

            # Roll for timeout
            timeout_pct = cmd_behavior.get("timeout_pct", 0.0)
            if random.random() * 100 < timeout_pct:
                # Sleep longer than visibility timeout to trigger redelivery
                await asyncio.sleep(DEFAULT_VISIBILITY_TIMEOUT_SECONDS * 1.5)

            # Success path - calculate duration from normal distribution
            min_ms = cmd_behavior.get("min_duration_ms", 0)
            max_ms = cmd_behavior.get("max_duration_ms", 0)

            if min_ms > 0 or max_ms > 0:
                duration_ms = _sample_duration(min_ms, max_ms)
                await asyncio.sleep(duration_ms / 1000)

            # Build result - include response_data if send_response is enabled
            result: dict[str, Any] = {
                "status": "success",
                "processed_at": time.time(),
            }

            # If send_response is enabled, include response data in result
            # This will be sent to the reply queue
            if cmd_behavior.get("send_response", False):
                response_data = cmd_behavior.get("response_data", {})
                result["response_data"] = response_data
                result["command_id"] = str(cmd.command_id)

            return result

        registry.register("e2e", "TestCommand", test_handler)
        return registry

    return _create


@pytest.fixture
async def worker(
    pool: AsyncConnectionPool,
    create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
) -> Worker:
    """Create a Worker with test handler registry."""
    registry = create_handler_registry({})  # Default: all success
    return Worker(
        pool,
        domain="e2e",
        registry=registry,
        visibility_timeout=30,
    )


@pytest.fixture
async def worker_task(worker: Worker) -> AsyncGenerator[asyncio.Task[None], None]:
    """Start a worker and yield the task."""
    task = asyncio.create_task(worker.run())
    # Give worker time to start
    await asyncio.sleep(0.1)
    yield task
    await worker.stop()
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
        registry = create_handler_registry({})  # Default: all success
        return Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=visibility_timeout,
            retry_policy=RetryPolicy(max_attempts=max_attempts, backoff_schedule=[1, 2, 5]),
        )

    return _create


@pytest.fixture
def reset_failure_counts() -> Callable[[], None]:
    """Reset the global failure counter between tests."""

    def _reset() -> None:
        _failure_counts.clear()

    return _reset


class ReplyAggregator:
    """Aggregates replies from a reply queue into batch summary.

    Reads messages from the reply queue and updates the batch_summary
    table with counts by outcome type (SUCCESS, FAILED, CANCELED).
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        reply_queue: str = "e2e__replies",
    ) -> None:
        """Initialize the reply aggregator.

        Args:
            pool: Database connection pool
            reply_queue: Name of the reply queue to read from
        """
        self._pool = pool
        self._pgmq = PgmqClient(pool)
        self._reply_queue = reply_queue
        self._batch_repo = BatchSummaryRepository(pool)

    async def process_replies(
        self,
        batch_id: UUID,
        timeout: float = 10.0,
        poll_interval: float = 0.1,
    ) -> BatchSummary:
        """Process all replies for a batch until complete or timeout.

        Reads from reply queue and updates batch_summary table.
        Returns when all expected replies are received or timeout.

        Args:
            batch_id: The batch ID to aggregate replies for
            timeout: Maximum time to wait for all replies
            poll_interval: Time between poll attempts

        Returns:
            Final BatchSummary with aggregated counts
        """
        deadline = time.time() + timeout

        while time.time() < deadline:
            # Read available messages
            messages = await self._pgmq.read(
                self._reply_queue,
                visibility_timeout=30,
                batch_size=10,
            )

            for msg in messages:
                await self._process_message(batch_id, msg.msg_id, msg.message)

            # Check if batch is complete
            summary = await self._batch_repo.get_by_batch_id(batch_id)
            if summary and summary.is_complete:
                return summary

            await asyncio.sleep(poll_interval)

        # Return current state on timeout
        summary = await self._batch_repo.get_by_batch_id(batch_id)
        if summary is None:
            raise RuntimeError(f"Batch summary not found for {batch_id}")
        return summary

    async def _process_message(
        self,
        batch_id: UUID,
        msg_id: int,
        message: dict[str, Any],
    ) -> None:
        """Process a single reply message.

        Updates the appropriate counter based on outcome.
        """
        outcome = message.get("outcome", "UNKNOWN")

        async with self._pool.connection() as conn:
            # Update count based on outcome
            if outcome == "SUCCESS":
                await self._batch_repo.increment_success(batch_id)
            elif outcome == "FAILED":
                await self._batch_repo.increment_failed(batch_id)
            elif outcome == "CANCELED":
                await self._batch_repo.increment_canceled(batch_id)

            # Delete the message from the queue
            await self._pgmq.delete(self._reply_queue, msg_id, conn)


@pytest.fixture
async def batch_summary_repo(
    pool: AsyncConnectionPool,
) -> BatchSummaryRepository:
    """Create a BatchSummaryRepository for tests."""
    return BatchSummaryRepository(pool)


@pytest.fixture
async def reply_aggregator(
    pool: AsyncConnectionPool,
) -> ReplyAggregator:
    """Create a ReplyAggregator for tests."""
    return ReplyAggregator(pool, reply_queue="e2e__replies")


@pytest.fixture
async def cleanup_reply_queue(
    pool: AsyncConnectionPool,
) -> AsyncGenerator[None, None]:
    """Clean up reply queue and batch summary before and after tests."""
    # Cleanup before test
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM pgmq.q_e2e__replies")
        await conn.execute("DELETE FROM e2e.batch_summary")
    yield
    # Cleanup after test
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM pgmq.q_e2e__replies")
        await conn.execute("DELETE FROM e2e.batch_summary")
