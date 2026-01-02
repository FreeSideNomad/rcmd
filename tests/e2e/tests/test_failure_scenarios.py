"""E2E tests for failure scenarios (S024).

These tests verify error handling, retries, and TSQ functionality
work correctly using the test command behavior specification.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from commandbus.models import CommandStatus
from commandbus.worker import Worker

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from psycopg_pool import AsyncConnectionPool

    from commandbus.bus import CommandBus
    from commandbus.handler import HandlerRegistry
    from commandbus.ops.troubleshooting import TroubleshootingQueue


@pytest.mark.e2e
class TestPermanentFailure:
    """E2E tests for permanent failure scenarios."""

    @pytest.mark.asyncio
    async def test_permanent_failure_moves_to_tsq(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        wait_for_tsq: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test permanent failure goes directly to TSQ.

        Verifies:
        - Command with fail_permanent behavior goes to TSQ
        - Error details are preserved
        - Audit trail shows MOVED_TO_TSQ event
        """
        command_id = uuid4()

        # Create worker with max_attempts=3
        registry = create_handler_registry({"type": "success"})
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
            concurrency=1,
            max_attempts=3,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                data={
                    "behavior": {
                        "type": "fail_permanent",
                        "error_code": "INVALID_ACCOUNT",
                        "error_message": "Account does not exist",
                    }
                },
            )

            await wait_for_tsq(command_id, timeout=10)

            # Verify final status
            cmd = await command_bus.get_command("e2e", command_id)
            assert cmd is not None
            assert cmd.status == CommandStatus.IN_TROUBLESHOOTING_QUEUE
            assert cmd.last_error_code == "INVALID_ACCOUNT"
            assert cmd.last_error_msg == "Account does not exist"

            # Verify audit trail
            events = await command_bus.get_audit_trail(command_id, domain="e2e")
            event_types = [e.event_type for e in events]
            assert "MOVED_TO_TSQ" in event_types

        finally:
            worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task

    @pytest.mark.asyncio
    async def test_error_details_preserved(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        wait_for_tsq: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test that error details are preserved in TSQ.

        Verifies:
        - error_code is preserved
        - error_message is preserved
        - error_type is preserved
        """
        command_id = uuid4()

        registry = create_handler_registry({"type": "success"})
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
            concurrency=1,
            max_attempts=1,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                data={
                    "behavior": {
                        "type": "fail_permanent",
                        "error_code": "VALIDATION_ERROR",
                        "error_message": "Missing required field: email",
                    }
                },
            )

            await wait_for_tsq(command_id, timeout=10)

            cmd = await command_bus.get_command("e2e", command_id)
            assert cmd is not None
            assert cmd.last_error_type == "PERMANENT"
            assert cmd.last_error_code == "VALIDATION_ERROR"
            assert cmd.last_error_msg == "Missing required field: email"

        finally:
            worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task


@pytest.mark.e2e
class TestTransientFailure:
    """E2E tests for transient failure scenarios."""

    @pytest.mark.asyncio
    async def test_transient_then_succeed(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        wait_for_completion: Callable[[UUID, float], Any],
        reset_failure_counts: Callable[[], None],
        cleanup_db: None,
    ) -> None:
        """Test transient failures followed by success.

        Verifies:
        - Command fails twice then succeeds on attempt 3
        - Final status is COMPLETED
        - Attempts count matches expected
        """
        command_id = uuid4()
        reset_failure_counts()

        registry = create_handler_registry({"type": "success"})
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
            concurrency=1,
            max_attempts=5,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                data={
                    "behavior": {
                        "type": "fail_transient_then_succeed",
                        "transient_failures": 2,
                        "error_code": "TIMEOUT",
                    }
                },
            )

            await wait_for_completion(command_id, timeout=30)

            cmd = await command_bus.get_command("e2e", command_id)
            assert cmd is not None
            assert cmd.status == CommandStatus.COMPLETED
            # Attempts should be 3 (2 failures + 1 success)
            assert cmd.attempts == 3

        finally:
            worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task

    @pytest.mark.asyncio
    async def test_retry_exhaustion(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        wait_for_tsq: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test transient failures exhaust retries.

        Verifies:
        - Command fails max_attempts times
        - Command moves to TSQ after retry exhaustion
        - Audit trail shows RETRY_EXHAUSTED event
        """
        command_id = uuid4()

        registry = create_handler_registry({"type": "success"})
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
            concurrency=1,
            max_attempts=3,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                data={
                    "behavior": {
                        "type": "fail_transient",
                        "error_code": "SERVICE_UNAVAILABLE",
                    }
                },
            )

            await wait_for_tsq(command_id, timeout=30)

            cmd = await command_bus.get_command("e2e", command_id)
            assert cmd is not None
            assert cmd.status == CommandStatus.IN_TROUBLESHOOTING_QUEUE
            assert cmd.attempts == 3

            # Verify audit trail
            events = await command_bus.get_audit_trail(command_id, domain="e2e")
            event_types = [e.event_type for e in events]
            assert "RETRY_EXHAUSTED" in event_types

        finally:
            worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task


@pytest.mark.e2e
class TestTSQOperations:
    """E2E tests for TSQ operator operations."""

    @pytest.mark.asyncio
    async def test_operator_retry(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        tsq: TroubleshootingQueue,
        wait_for_tsq: Callable[[UUID, float], Any],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test operator retry from TSQ.

        Verifies:
        - Command in TSQ can be retried
        - After retry, command is processed again
        - Audit trail shows OPERATOR_RETRY event
        """
        command_id = uuid4()

        registry = create_handler_registry({"type": "success"})
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
            concurrency=1,
            max_attempts=1,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            # Send command that will fail permanently
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                data={
                    "behavior": {
                        "type": "fail_permanent",
                        "error_code": "TEMP_ISSUE",
                    }
                },
            )

            await wait_for_tsq(command_id, timeout=10)

            # Update the command data to succeed on retry
            async with pool.connection() as conn:
                new_data = json.dumps({"behavior": {"type": "success"}})
                await conn.execute(
                    "UPDATE command_bus_command SET data = %s WHERE command_id = %s",
                    (new_data, command_id),
                )

            # Also update the archived message to succeed
            async with pool.connection() as conn:
                await conn.execute(
                    """
                    UPDATE pgmq.a_e2e__commands
                    SET message = jsonb_set(message, '{data}', %s::jsonb)
                    WHERE message->>'command_id' = %s
                    """,
                    ('{"behavior": {"type": "success"}}', str(command_id)),
                )

            # Operator retries the command
            await tsq.operator_retry(
                domain="e2e",
                command_id=command_id,
                operator="test-operator",
            )

            await wait_for_completion(command_id, timeout=10)

            cmd = await command_bus.get_command("e2e", command_id)
            assert cmd is not None
            assert cmd.status == CommandStatus.COMPLETED

            # Verify audit trail
            events = await command_bus.get_audit_trail(command_id, domain="e2e")
            event_types = [e.event_type for e in events]
            assert "OPERATOR_RETRY" in event_types

        finally:
            worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task

    @pytest.mark.asyncio
    async def test_operator_cancel(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        tsq: TroubleshootingQueue,
        wait_for_tsq: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test operator cancel from TSQ.

        Verifies:
        - Command in TSQ can be cancelled
        - Status becomes CANCELED
        - Audit trail shows OPERATOR_CANCEL event
        """
        command_id = uuid4()

        registry = create_handler_registry({"type": "success"})
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
            concurrency=1,
            max_attempts=1,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                data={
                    "behavior": {
                        "type": "fail_permanent",
                        "error_code": "UNRECOVERABLE",
                    }
                },
            )

            await wait_for_tsq(command_id, timeout=10)

            # Operator cancels the command
            await tsq.operator_cancel(
                domain="e2e",
                command_id=command_id,
                reason="Test cancellation - no longer needed",
                operator="test-operator",
            )

            cmd = await command_bus.get_command("e2e", command_id)
            assert cmd is not None
            assert cmd.status == CommandStatus.CANCELED

            # Verify audit trail
            events = await command_bus.get_audit_trail(command_id, domain="e2e")
            event_types = [e.event_type for e in events]
            assert "OPERATOR_CANCEL" in event_types

        finally:
            worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task

    @pytest.mark.asyncio
    async def test_operator_complete(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        tsq: TroubleshootingQueue,
        wait_for_tsq: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test operator complete from TSQ.

        Verifies:
        - Command in TSQ can be manually completed
        - Status becomes COMPLETED
        - Audit trail shows OPERATOR_COMPLETE event
        """
        command_id = uuid4()

        registry = create_handler_registry({"type": "success"})
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
            concurrency=1,
            max_attempts=1,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                data={
                    "behavior": {
                        "type": "fail_permanent",
                        "error_code": "NEEDS_MANUAL",
                    }
                },
            )

            await wait_for_tsq(command_id, timeout=10)

            # Operator manually completes the command
            await tsq.operator_complete(
                domain="e2e",
                command_id=command_id,
                result_data={"manually_resolved": True, "resolution": "Fixed externally"},
                operator="test-operator",
            )

            cmd = await command_bus.get_command("e2e", command_id)
            assert cmd is not None
            assert cmd.status == CommandStatus.COMPLETED

            # Verify audit trail
            events = await command_bus.get_audit_trail(command_id, domain="e2e")
            event_types = [e.event_type for e in events]
            assert "OPERATOR_COMPLETE" in event_types

        finally:
            worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task

    @pytest.mark.asyncio
    async def test_tsq_list_commands(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        tsq: TroubleshootingQueue,
        wait_for_tsq: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test listing commands in TSQ.

        Verifies:
        - Commands in TSQ can be listed
        - Multiple commands are returned correctly
        """
        command_ids = [uuid4(), uuid4()]

        registry = create_handler_registry({"type": "success"})
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
            concurrency=2,
            max_attempts=1,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            # Send multiple failing commands
            for cmd_id in command_ids:
                await command_bus.send(
                    domain="e2e",
                    command_type="TestCommand",
                    command_id=cmd_id,
                    data={
                        "behavior": {
                            "type": "fail_permanent",
                            "error_code": "BATCH_FAILURE",
                        }
                    },
                )

            # Wait for both to reach TSQ
            for cmd_id in command_ids:
                await wait_for_tsq(cmd_id, timeout=10)

            # List TSQ items
            items = await tsq.list_troubleshooting(domain="e2e")

            assert len(items) >= 2
            tsq_cmd_ids = {item.command_id for item in items}
            for cmd_id in command_ids:
                assert cmd_id in tsq_cmd_ids

        finally:
            worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task
