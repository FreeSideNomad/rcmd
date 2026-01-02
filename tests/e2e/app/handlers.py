"""E2E test command handlers using @handler decorator (F007 pattern)."""

import asyncio
from typing import Any

from psycopg_pool import AsyncConnectionPool

from commandbus import Command, HandlerContext, handler
from commandbus.exceptions import PermanentCommandError, TransientCommandError

from .models import TestCommandRepository


class TestCommandHandlers:
    """E2E test command handlers using @handler decorator.

    This class demonstrates the F007 pattern:
    - Constructor-injected dependencies (pool)
    - @handler decorator marks methods as command handlers
    - Stateless design (no mutable instance state beyond dependencies)
    - Handler methods use ctx.conn for transaction participation
    """

    def __init__(self, pool: AsyncConnectionPool) -> None:
        """Initialize with database pool dependency."""
        self._pool = pool

    @handler(domain="e2e", command_type="TestCommand")
    async def handle_test_command(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle test command based on behavior specification.

        Behavior types:
        - success: Complete successfully
        - fail_permanent: Raise PermanentCommandError
        - fail_transient: Raise TransientCommandError
        - fail_transient_then_succeed: Fail transiently N times, then succeed
        - timeout: Simulate long execution
        """
        repo = TestCommandRepository(self._pool)

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
