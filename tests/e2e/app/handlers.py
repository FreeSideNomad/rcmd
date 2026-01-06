"""E2E test command handlers using @handler decorator (F007 pattern)."""

import asyncio
import random
from typing import Any

from psycopg_pool import AsyncConnectionPool

from commandbus import Command, HandlerContext, handler
from commandbus.exceptions import PermanentCommandError, TransientCommandError

from .models import TestCommandRepository

# Default visibility timeout for timeout simulation
DEFAULT_VISIBILITY_TIMEOUT_SECONDS = 30


def _sample_duration(min_ms: int, max_ms: int) -> float:
    """Sample duration from normal distribution, clamped to [min, max].

    Uses a normal distribution with:
    - Mean at midpoint of range
    - Standard deviation = range/6 (99.7% of values within range)
    """
    if min_ms == max_ms:
        return float(min_ms)

    if min_ms > max_ms:
        min_ms, max_ms = max_ms, min_ms

    mean = (min_ms + max_ms) / 2
    # 6 sigma covers 99.7% of values
    std_dev = (max_ms - min_ms) / 6

    sample = random.gauss(mean, std_dev)
    return max(min_ms, min(max_ms, sample))


class NoOpHandlers:
    """No-operation handlers for performance benchmarking.

    These handlers do nothing except return immediately, allowing measurement
    of raw command bus throughput without handler overhead.
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Initialize with database pool dependency (unused but required for consistency)."""
        self._pool = pool

    @handler(domain="e2e", command_type="NoOp")
    async def handle_no_op(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle NoOp command - immediately returns success with no processing."""
        return {"status": "success", "no_op": True}


class TestCommandHandlers:
    """E2E test command handlers using probabilistic behavior evaluation.

    This class demonstrates the F007 pattern:
    - Constructor-injected dependencies (pool)
    - @handler decorator marks methods as command handlers
    - Stateless design (no mutable instance state beyond dependencies)
    - Handlers manage their own database transactions

    Probabilistic Behavior Evaluation:
    Commands are evaluated sequentially in this order:
    1. Roll for fail_permanent_pct -> PermanentCommandError
    2. Roll for fail_transient_pct -> TransientCommandError
    3. Roll for timeout_pct -> Sleep > visibility_timeout, then success
    4. Otherwise -> Success with duration from normal distribution
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Initialize with database pool dependency."""
        self._pool = pool

    @handler(domain="e2e", command_type="TestCommand")
    async def handle_test_command(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle test command based on probabilistic behavior specification.

        Probabilities are evaluated sequentially:
        - fail_permanent_pct: Chance of permanent failure (0-100%)
        - fail_transient_pct: Chance of transient failure (0-100%)
        - timeout_pct: Chance of timeout behavior (0-100%)
        - If none trigger, command succeeds with duration sampled from
          normal distribution between min_duration_ms and max_duration_ms
        """
        repo = TestCommandRepository(self._pool)

        # Read behavior configuration
        test_cmd = await repo.get_by_command_id(cmd.command_id)
        if not test_cmd:
            raise PermanentCommandError(
                code="TEST_COMMAND_NOT_FOUND",
                message=f"Test command {cmd.command_id} not found in test_command table",
            )

        behavior = test_cmd.behavior

        # Roll for permanent failure
        fail_permanent_pct = behavior.get("fail_permanent_pct", 0.0)
        if random.random() * 100 < fail_permanent_pct:
            error_code = behavior.get("error_code", "PERMANENT_ERROR")
            error_message = behavior.get("error_message", "Probabilistic permanent failure")
            raise PermanentCommandError(code=error_code, message=error_message)

        # Roll for transient failure
        fail_transient_pct = behavior.get("fail_transient_pct", 0.0)
        if random.random() * 100 < fail_transient_pct:
            error_code = behavior.get("error_code", "TRANSIENT_ERROR")
            error_message = behavior.get("error_message", "Probabilistic transient failure")
            raise TransientCommandError(code=error_code, message=error_message)

        # Roll for timeout
        timeout_pct = behavior.get("timeout_pct", 0.0)
        if random.random() * 100 < timeout_pct:
            # Sleep longer than visibility timeout to trigger redelivery
            # This simulates a command that takes too long to process
            await asyncio.sleep(DEFAULT_VISIBILITY_TIMEOUT_SECONDS * 1.5)

        # Success path - calculate duration from normal distribution
        min_ms = behavior.get("min_duration_ms", 0)
        max_ms = behavior.get("max_duration_ms", 0)

        if min_ms > 0 or max_ms > 0:
            duration_ms = _sample_duration(min_ms, max_ms)
            await asyncio.sleep(duration_ms / 1000)

        # Update attempt count and mark processed
        attempt = await repo.increment_attempts(cmd.command_id)
        result: dict[str, Any] = {"status": "success", "attempt": attempt}

        # Include response_data if send_response is enabled
        if behavior.get("send_response", False):
            response_data = behavior.get("response_data", {})
            if response_data:
                result["response_data"] = response_data

        await repo.mark_processed(cmd.command_id, result)
        return result
