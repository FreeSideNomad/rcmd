"""Native synchronous E2E test command handlers.

These handlers use sync repositories and sync ConnectionPool directly,
without any async wrappers or event loops.
"""

from __future__ import annotations

import logging
import random
import time
from typing import TYPE_CHECKING, Any

from commandbus import Command, HandlerContext, HandlerRegistry
from commandbus.exceptions import (
    BusinessRuleException,
    PermanentCommandError,
    TransientCommandError,
)

from ..sync_models import SyncTestCommandRepository

if TYPE_CHECKING:
    from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)

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


class SyncNoOpHandlers:
    """Synchronous no-operation handlers for performance benchmarking.

    These handlers do nothing except return immediately, allowing measurement
    of raw command bus throughput without handler overhead.
    """

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        """Initialize with sync database pool."""
        self._pool = pool

    def handle_no_op(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle NoOp command - immediately returns success with no processing."""
        return {"status": "success", "no_op": True}


class SyncTestCommandHandlers:
    """Native synchronous E2E test command handlers.

    Uses sync repositories with sync ConnectionPool for database operations.
    No async wrappers or event loops.
    """

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        """Initialize with sync database pool."""
        self._pool = pool
        self._repo = SyncTestCommandRepository(pool)

    def handle_test_command(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle test command based on probabilistic behavior specification.

        Probabilities are evaluated sequentially:
        - fail_permanent_pct: Chance of permanent failure (0-100%)
        - fail_transient_pct: Chance of transient failure (0-100%)
        - fail_business_rule_pct: Chance of business rule failure (0-100%)
        - timeout_pct: Chance of timeout behavior (0-100%)
        - If none trigger, command succeeds with duration sampled from
          normal distribution between min_duration_ms and max_duration_ms
        """
        # Read behavior configuration
        test_cmd = self._repo.get_by_command_id(cmd.command_id)
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

        # Roll for business rule failure
        fail_business_rule_pct = behavior.get("fail_business_rule_pct", 0.0)
        if random.random() * 100 < fail_business_rule_pct:
            error_code = behavior.get("error_code", "BUSINESS_RULE_VIOLATION")
            error_message = behavior.get("error_message", "Probabilistic business rule failure")
            raise BusinessRuleException(code=error_code, message=error_message)

        # Roll for timeout
        timeout_pct = behavior.get("timeout_pct", 0.0)
        if random.random() * 100 < timeout_pct:
            # Sleep longer than visibility timeout to trigger redelivery
            time.sleep(DEFAULT_VISIBILITY_TIMEOUT_SECONDS * 1.5)

        # Success path - calculate duration from normal distribution
        min_ms = behavior.get("min_duration_ms", 0)
        max_ms = behavior.get("max_duration_ms", 0)

        if min_ms > 0 or max_ms > 0:
            duration_ms = _sample_duration(min_ms, max_ms)
            time.sleep(duration_ms / 1000)

        # Update attempt count and mark processed
        attempt = self._repo.increment_attempts(cmd.command_id)
        result: dict[str, Any] = {"status": "success", "attempt": attempt}

        # Include response_data if send_response is enabled
        if behavior.get("send_response", False):
            response_data = behavior.get("response_data", {})
            if response_data:
                result["response_data"] = response_data

        self._repo.mark_processed(cmd.command_id, result)
        return result


class SyncReportingHandlers:
    """Synchronous reporting domain handlers."""

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        """Initialize with sync database pool."""
        self._pool = pool
        self._repo = SyncTestCommandRepository(pool)

    def _get_behavior(self, command_id: Any) -> dict[str, Any]:
        """Get behavior configuration for a command."""
        test_cmd = self._repo.get_by_command_id(command_id)
        return test_cmd.behavior if test_cmd else {}

    def _handle_probabilistic(self, cmd: Command, behavior: dict[str, Any]) -> None:
        """Apply probabilistic behavior (failures, delay) based on configuration."""
        # Roll for permanent failure
        fail_permanent_pct = behavior.get("fail_permanent_pct", 0.0)
        if random.random() * 100 < fail_permanent_pct:
            error_code = behavior.get("error_code", "REPORTING_ERROR")
            error_message = behavior.get("error_message", "Probabilistic failure")
            raise PermanentCommandError(code=error_code, message=error_message)

        # Roll for transient failure
        fail_transient_pct = behavior.get("fail_transient_pct", 0.0)
        if random.random() * 100 < fail_transient_pct:
            error_code = behavior.get("error_code", "REPORTING_TRANSIENT")
            error_message = behavior.get("error_message", "Probabilistic transient")
            raise TransientCommandError(code=error_code, message=error_message)

        # Roll for business rule failure
        fail_business_rule_pct = behavior.get("fail_business_rule_pct", 0.0)
        if random.random() * 100 < fail_business_rule_pct:
            error_code = behavior.get("error_code", "REPORTING_BUSINESS_RULE")
            error_message = behavior.get("error_message", "Probabilistic business rule failure")
            raise BusinessRuleException(code=error_code, message=error_message)

        # Duration
        min_ms = behavior.get("min_duration_ms", 0)
        max_ms = behavior.get("max_duration_ms", 0)
        if min_ms > 0 or max_ms > 0:
            duration_ms = _sample_duration(min_ms, max_ms)
            time.sleep(duration_ms / 1000.0)

    def handle_generate_report(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle GenerateReport command for process management testing."""
        # Read behavior configuration if exists
        test_cmd = self._repo.get_by_command_id(cmd.command_id)

        if test_cmd:
            behavior = test_cmd.behavior

            # Roll for permanent failure
            fail_permanent_pct = behavior.get("fail_permanent_pct", 0.0)
            if random.random() * 100 < fail_permanent_pct:
                error_code = behavior.get("error_code", "REPORT_GENERATION_FAILED")
                error_message = behavior.get("error_message", "Failed to generate report")
                raise PermanentCommandError(code=error_code, message=error_message)

            # Roll for transient failure
            fail_transient_pct = behavior.get("fail_transient_pct", 0.0)
            if random.random() * 100 < fail_transient_pct:
                error_code = behavior.get("error_code", "REPORT_GENERATION_TIMEOUT")
                error_message = behavior.get("error_message", "Report generation timed out")
                raise TransientCommandError(code=error_code, message=error_message)

            # Roll for business rule failure
            fail_business_rule_pct = behavior.get("fail_business_rule_pct", 0.0)
            if random.random() * 100 < fail_business_rule_pct:
                error_code = behavior.get("error_code", "REPORT_BUSINESS_RULE")
                error_message = behavior.get("error_message", "Report business rule violation")
                raise BusinessRuleException(code=error_code, message=error_message)

            # Simulate processing time
            min_ms = behavior.get("min_duration_ms", 10)
            max_ms = behavior.get("max_duration_ms", 100)
            duration_ms = _sample_duration(min_ms, max_ms)
            time.sleep(duration_ms / 1000)

            # Update attempt count
            self._repo.increment_attempts(cmd.command_id)

        # Extract statement IDs from command data
        statement_ids = cmd.data.get("statement_ids", [])
        report_type = cmd.data.get("report_type", "summary")

        return {
            "status": "success",
            "report_type": report_type,
            "statement_count": len(statement_ids),
            "statement_ids": statement_ids,
        }

    def handle_statement_query(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle StatementQuery command for process manager."""
        import uuid

        behavior = self._get_behavior(cmd.command_id)
        self._handle_probabilistic(cmd, behavior)
        return {"result_path": f"s3://bucket/query/{uuid.uuid4()}.json"}

    def handle_statement_aggregation(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle StatementDataAggregation command for process manager."""
        import uuid

        behavior = self._get_behavior(cmd.command_id)
        self._handle_probabilistic(cmd, behavior)
        return {"result_path": f"s3://bucket/aggregated/{uuid.uuid4()}.json"}

    def handle_statement_render(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle StatementRender command for process manager."""
        import uuid

        behavior = self._get_behavior(cmd.command_id)
        self._handle_probabilistic(cmd, behavior)
        output_type = cmd.data.get("output_type", "pdf")
        return {"result_path": f"s3://bucket/rendered/{uuid.uuid4()}.{output_type}"}


def create_sync_handler_registry(pool: ConnectionPool[Any]) -> HandlerRegistry:
    """Create handler registry with native sync handlers.

    This creates handlers that use sync repositories directly with the
    sync ConnectionPool - no async wrappers or event loops.

    Args:
        pool: Sync ConnectionPool for database operations

    Returns:
        HandlerRegistry with sync handlers registered
    """
    registry = HandlerRegistry()

    # Create handler instances
    no_op_handlers = SyncNoOpHandlers(pool)
    test_handlers = SyncTestCommandHandlers(pool)
    reporting_handlers = SyncReportingHandlers(pool)

    # Register sync handlers directly
    registry.register_sync("e2e", "NoOp", no_op_handlers.handle_no_op)
    registry.register_sync("e2e", "TestCommand", test_handlers.handle_test_command)
    registry.register_sync("reporting", "GenerateReport", reporting_handlers.handle_generate_report)
    registry.register_sync("reporting", "StatementQuery", reporting_handlers.handle_statement_query)
    registry.register_sync(
        "reporting", "StatementDataAggregation", reporting_handlers.handle_statement_aggregation
    )
    registry.register_sync(
        "reporting", "StatementRender", reporting_handlers.handle_statement_render
    )

    logger.info(
        "Created sync handler registry with native handlers: "
        "e2e.NoOp, e2e.TestCommand, reporting.GenerateReport, "
        "reporting.StatementQuery, reporting.StatementDataAggregation, reporting.StatementRender"
    )

    return registry


__all__ = [
    "SyncNoOpHandlers",
    "SyncReportingHandlers",
    "SyncTestCommandHandlers",
    "create_sync_handler_registry",
]
