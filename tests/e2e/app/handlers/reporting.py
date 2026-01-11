"""E2E Reporting domain command handlers."""

import asyncio
import random
import uuid
from typing import Any

from commandbus import Command, HandlerContext, handler
from commandbus.exceptions import (
    BusinessRuleException,
    PermanentCommandError,
    TransientCommandError,
)

from ..models import TestCommandRepository
from .base import _sample_duration


class ReportingHandlers:
    """Handlers for the 'reporting' domain, supporting probabilistic behavior."""

    def __init__(self, pool: Any) -> None:
        """Initialize with database pool dependency."""
        self._pool = pool

    async def _get_behavior(self, command_id: uuid.UUID) -> dict[str, Any]:
        """Get behavior configuration for a command."""
        repo = TestCommandRepository(self._pool)
        test_cmd = await repo.get_by_command_id(command_id)
        return test_cmd.behavior if test_cmd else {}

    async def _handle_probabilistic(self, cmd: Command, behavior: dict[str, Any]) -> None:
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
            await asyncio.sleep(duration_ms / 1000.0)

    @handler(domain="reporting", command_type="StatementQuery")
    async def handle_query(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle StatementQuery command."""
        behavior = await self._get_behavior(cmd.command_id)
        await self._handle_probabilistic(cmd, behavior)
        return {"result_path": f"s3://bucket/query/{uuid.uuid4()}.json"}

    @handler(domain="reporting", command_type="StatementDataAggregation")
    async def handle_aggregation(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle StatementDataAggregation command."""
        behavior = await self._get_behavior(cmd.command_id)
        await self._handle_probabilistic(cmd, behavior)
        return {"result_path": f"s3://bucket/aggregated/{uuid.uuid4()}.json"}

    @handler(domain="reporting", command_type="StatementRender")
    async def handle_render(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle StatementRender command."""
        behavior = await self._get_behavior(cmd.command_id)
        await self._handle_probabilistic(cmd, behavior)
        output_type = cmd.data.get("output_type", "pdf")
        return {"result_path": f"s3://bucket/rendered/{uuid.uuid4()}.{output_type}"}
