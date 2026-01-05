"""E2E tests for reply queue scenarios.

These tests verify the complete command lifecycle including reply queue
functionality, from sending commands with reply_to through aggregating
replies in the batch_summary table.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest

from commandbus.models import CommandStatus
from commandbus.pgmq.client import PgmqClient
from commandbus.worker import Worker

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from psycopg_pool import AsyncConnectionPool

    from commandbus.bus import CommandBus
    from commandbus.handler import HandlerRegistry
    from tests.e2e.app.models import BatchSummaryRepository

    from .conftest import ReplyAggregator


@pytest.mark.e2e
class TestReplyQueueScenarios:
    """E2E tests for reply queue functionality."""

    @pytest.mark.asyncio
    async def test_single_command_with_reply(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        wait_for_completion: Callable[[UUID, float], Any],
        batch_summary_repo: BatchSummaryRepository,
        reply_aggregator: ReplyAggregator,
        cleanup_db: None,
        cleanup_reply_queue: None,
    ) -> None:
        """Test single command with reply_to sends reply to queue.

        Verifies:
        - Command is sent with reply_to configured
        - Worker processes and sends SUCCESS reply
        - Reply appears in reply queue with correct data
        - Batch summary is updated with success count
        """
        batch_id = uuid4()
        command_id = uuid4()

        # Create batch summary to track this reply
        await batch_summary_repo.create(batch_id, total_expected=1)

        # Create worker
        registry = create_handler_registry(None)
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            # Send command with reply_to and send_response behavior
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                data={
                    "behavior": {
                        "send_response": True,
                        "response_data": {"processed": True},
                    }
                },
                reply_to="e2e__replies",
            )

            # Wait for command completion
            await wait_for_completion(command_id, timeout=10)

            # Process replies and verify batch summary
            summary = await reply_aggregator.process_replies(batch_id, timeout=5)

            assert summary.success_count == 1
            assert summary.failed_count == 0
            assert summary.canceled_count == 0
            assert summary.is_complete

        finally:
            await worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()

    @pytest.mark.asyncio
    async def test_batch_commands_with_replies(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        wait_for_completion: Callable[[UUID, float], Any],
        batch_summary_repo: BatchSummaryRepository,
        reply_aggregator: ReplyAggregator,
        cleanup_db: None,
        cleanup_reply_queue: None,
    ) -> None:
        """Test batch of commands with reply_to sends multiple replies.

        Verifies:
        - Multiple commands sent with same reply_to
        - All commands complete successfully
        - All replies aggregated in batch summary
        - Batch marked complete when all replies received
        """
        batch_id = uuid4()
        num_commands = 5
        command_ids = [uuid4() for _ in range(num_commands)]

        # Create batch summary
        await batch_summary_repo.create(batch_id, total_expected=num_commands)

        # Create worker with concurrency
        registry = create_handler_registry(None)
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
        )

        worker_task = asyncio.create_task(worker.run(concurrency=3))
        await asyncio.sleep(0.1)

        try:
            # Send all commands
            for cmd_id in command_ids:
                await command_bus.send(
                    domain="e2e",
                    command_type="TestCommand",
                    command_id=cmd_id,
                    data={
                        "behavior": {
                            "send_response": True,
                            "response_data": {"batch_id": str(batch_id)},
                        }
                    },
                    reply_to="e2e__replies",
                )

            # Wait for all to complete
            for cmd_id in command_ids:
                await wait_for_completion(cmd_id, timeout=15)

            # Process all replies
            summary = await reply_aggregator.process_replies(batch_id, timeout=10)

            assert summary.success_count == num_commands
            assert summary.failed_count == 0
            assert summary.canceled_count == 0
            assert summary.is_complete
            assert summary.completed_at is not None

        finally:
            await worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()

    @pytest.mark.asyncio
    async def test_reply_contains_result_data(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
        cleanup_reply_queue: None,
    ) -> None:
        """Test that reply contains handler result data.

        Verifies:
        - Handler returns result with response_data
        - Reply message includes the result
        """
        command_id = uuid4()
        expected_data = {"key": "value", "number": 42}

        # Create worker
        registry = create_handler_registry(None)
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            # Send command
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                data={
                    "behavior": {
                        "send_response": True,
                        "response_data": expected_data,
                    }
                },
                reply_to="e2e__replies",
            )

            # Wait for completion
            await wait_for_completion(command_id, timeout=10)

            # Read reply directly from queue
            pgmq = PgmqClient(pool)
            await asyncio.sleep(0.2)  # Small delay for reply to be enqueued

            messages = await pgmq.read("e2e__replies", visibility_timeout=30, batch_size=1)

            assert len(messages) == 1
            reply = messages[0].message

            assert reply["command_id"] == str(command_id)
            assert reply["outcome"] == "SUCCESS"
            assert reply["result"] is not None
            assert reply["result"]["response_data"] == expected_data

        finally:
            await worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()

    @pytest.mark.asyncio
    async def test_command_without_reply_to_no_reply(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
        cleanup_reply_queue: None,
    ) -> None:
        """Test that command without reply_to does not send reply.

        Verifies:
        - Command completes successfully
        - No message appears in reply queue
        """
        command_id = uuid4()

        # Create worker
        registry = create_handler_registry(None)
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            # Send command WITHOUT reply_to
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                data={"behavior": {}},
                # No reply_to parameter
            )

            # Wait for completion
            await wait_for_completion(command_id, timeout=10)

            # Verify command completed
            cmd = await command_bus.get_command("e2e", command_id)
            assert cmd is not None
            assert cmd.status == CommandStatus.COMPLETED

            # Check reply queue is empty
            pgmq = PgmqClient(pool)
            await asyncio.sleep(0.2)

            messages = await pgmq.read("e2e__replies", visibility_timeout=30, batch_size=10)
            assert len(messages) == 0

        finally:
            await worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()

    @pytest.mark.asyncio
    async def test_reply_includes_correlation_id(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
        cleanup_reply_queue: None,
    ) -> None:
        """Test that reply includes correlation_id when set.

        Verifies:
        - Command sent with correlation_id
        - Reply contains the same correlation_id
        """
        command_id = uuid4()
        correlation_id = uuid4()

        # Create worker
        registry = create_handler_registry(None)
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)

        try:
            # Send command with correlation_id
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=command_id,
                correlation_id=correlation_id,
                data={"behavior": {"send_response": True}},
                reply_to="e2e__replies",
            )

            # Wait for completion
            await wait_for_completion(command_id, timeout=10)

            # Read reply
            pgmq = PgmqClient(pool)
            await asyncio.sleep(0.2)

            messages = await pgmq.read("e2e__replies", visibility_timeout=30, batch_size=1)

            assert len(messages) == 1
            reply = messages[0].message

            assert reply["command_id"] == str(command_id)
            assert reply["correlation_id"] == str(correlation_id)
            assert reply["outcome"] == "SUCCESS"

        finally:
            await worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()
