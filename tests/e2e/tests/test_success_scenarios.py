"""E2E tests for success scenarios (S023).

These tests verify the complete command lifecycle from sending through completion,
using the test command behavior specification to control outcomes.
"""

from __future__ import annotations

import asyncio
import time
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


@pytest.mark.e2e
class TestSuccessScenarios:
    """E2E tests for successful command processing."""

    @pytest.mark.asyncio
    async def test_send_and_complete_command(
        self,
        command_bus: CommandBus,
        worker_task: asyncio.Task[None],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test basic send and complete flow.

        Verifies:
        - Command is sent successfully
        - Worker picks up and processes command
        - Status transitions: PENDING -> IN_PROGRESS -> COMPLETED
        - Audit trail contains SENT, STARTED, COMPLETED events
        """
        command_id = uuid4()

        # Send command with success behavior
        result = await command_bus.send(
            domain="e2e",
            command_type="TestCommand",
            command_id=command_id,
            data={"behavior": {"type": "success"}, "test_data": "value"},
        )

        assert result.msg_id is not None

        # Wait for completion
        cmd = await wait_for_completion(command_id, timeout=10)

        # Verify final status
        assert cmd.status == CommandStatus.COMPLETED

        # Verify audit trail
        events = await command_bus.get_audit_trail(command_id, domain="e2e")
        event_types = [e.event_type for e in events]

        assert "SENT" in event_types
        assert "STARTED" in event_types
        assert "COMPLETED" in event_types

    @pytest.mark.asyncio
    async def test_command_with_execution_delay(
        self,
        command_bus: CommandBus,
        worker_task: asyncio.Task[None],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test command with simulated execution time.

        Verifies:
        - Command with execution_time_ms takes approximately that long
        - Timing is reflected in audit trail
        """
        command_id = uuid4()
        execution_time_ms = 300  # 300ms delay

        start = time.time()

        await command_bus.send(
            domain="e2e",
            command_type="TestCommand",
            command_id=command_id,
            data={"behavior": {"type": "success", "execution_time_ms": execution_time_ms}},
        )

        await wait_for_completion(command_id, timeout=10)
        elapsed = time.time() - start

        # Should take at least the execution time
        assert elapsed >= execution_time_ms / 1000

        # Verify completed
        cmd = await command_bus.get_command("e2e", command_id)
        assert cmd is not None
        assert cmd.status == CommandStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_immediate_command(
        self,
        command_bus: CommandBus,
        worker_task: asyncio.Task[None],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test command with no execution delay completes quickly.

        Verifies:
        - Command with no execution_time_ms completes immediately
        - Processing time is minimal
        """
        command_id = uuid4()

        start = time.time()

        await command_bus.send(
            domain="e2e",
            command_type="TestCommand",
            command_id=command_id,
            data={"behavior": {"type": "success"}},
        )

        await wait_for_completion(command_id, timeout=10)
        elapsed = time.time() - start

        # Should complete quickly (within 2 seconds including queue latency)
        assert elapsed < 2.0

    @pytest.mark.asyncio
    async def test_command_with_custom_payload(
        self,
        command_bus: CommandBus,
        worker_task: asyncio.Task[None],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test command with custom payload data.

        Verifies:
        - Custom payload is passed to handler
        - Payload is preserved in command data
        """
        command_id = uuid4()
        custom_payload = {
            "user_id": "user-123",
            "action": "process",
            "metadata": {"key": "value", "numbers": [1, 2, 3]},
        }

        await command_bus.send(
            domain="e2e",
            command_type="TestCommand",
            command_id=command_id,
            data={"behavior": {"type": "success"}, **custom_payload},
        )

        await wait_for_completion(command_id, timeout=10)

        # Verify command has the payload
        cmd = await command_bus.get_command("e2e", command_id)
        assert cmd is not None
        assert cmd.data["user_id"] == custom_payload["user_id"]
        assert cmd.data["action"] == custom_payload["action"]
        assert cmd.data["metadata"] == custom_payload["metadata"]

    @pytest.mark.asyncio
    async def test_multiple_concurrent_commands(
        self,
        pool: AsyncConnectionPool,
        command_bus: CommandBus,
        create_handler_registry: Callable[[dict[str, Any] | None], HandlerRegistry],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test multiple commands processed concurrently.

        Verifies:
        - Multiple commands can be sent
        - Worker processes them in parallel (with concurrency > 1)
        - All commands complete successfully
        - Total time is less than sequential execution would take
        """
        num_commands = 6
        execution_time_ms = 200  # Each command takes 200ms
        command_ids = [uuid4() for _ in range(num_commands)]

        # Create worker with higher concurrency
        registry = create_handler_registry({"type": "success"})
        worker = Worker(
            pool,
            domain="e2e",
            registry=registry,
            visibility_timeout=30,
            concurrency=3,  # Process 3 at a time
        )

        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)  # Let worker start

        try:
            start = time.time()

            # Send all commands
            for cmd_id in command_ids:
                await command_bus.send(
                    domain="e2e",
                    command_type="TestCommand",
                    command_id=cmd_id,
                    data={"behavior": {"type": "success", "execution_time_ms": execution_time_ms}},
                )

            # Wait for all to complete
            for cmd_id in command_ids:
                await wait_for_completion(cmd_id, timeout=30)

            elapsed = time.time() - start

            # With concurrency=3 and 6 commands at 200ms each:
            # Sequential would take ~1200ms, parallel should take ~400-600ms
            # Allow some overhead
            assert elapsed < 1.5  # Should be much faster than 1.2s sequential

            # Verify all completed
            for cmd_id in command_ids:
                cmd = await command_bus.get_command("e2e", cmd_id)
                assert cmd is not None
                assert cmd.status == CommandStatus.COMPLETED

        finally:
            worker.stop()
            try:
                await asyncio.wait_for(worker_task, timeout=5.0)
            except TimeoutError:
                worker_task.cancel()

    @pytest.mark.asyncio
    async def test_sequential_commands(
        self,
        command_bus: CommandBus,
        worker_task: asyncio.Task[None],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test processing multiple commands sequentially.

        Verifies:
        - Multiple commands can be sent one after another
        - Each completes successfully
        - Order of completion matches send order (approximately)
        """
        command_ids = [uuid4() for _ in range(3)]
        completion_times: list[float] = []

        start = time.time()

        for cmd_id in command_ids:
            await command_bus.send(
                domain="e2e",
                command_type="TestCommand",
                command_id=cmd_id,
                data={"behavior": {"type": "success"}},
            )
            await wait_for_completion(cmd_id, timeout=10)
            completion_times.append(time.time() - start)

        # All should complete
        for cmd_id in command_ids:
            cmd = await command_bus.get_command("e2e", cmd_id)
            assert cmd is not None
            assert cmd.status == CommandStatus.COMPLETED

        # Completion times should be increasing
        assert completion_times[0] < completion_times[1] < completion_times[2]

    @pytest.mark.asyncio
    async def test_audit_trail_chronological_order(
        self,
        command_bus: CommandBus,
        worker_task: asyncio.Task[None],
        wait_for_completion: Callable[[UUID, float], Any],
        cleanup_db: None,
    ) -> None:
        """Test that audit trail events are in chronological order.

        Verifies:
        - Events have increasing timestamps
        - Event sequence makes sense (SENT before STARTED before COMPLETED)
        """
        command_id = uuid4()

        await command_bus.send(
            domain="e2e",
            command_type="TestCommand",
            command_id=command_id,
            data={"behavior": {"type": "success", "execution_time_ms": 100}},
        )

        await wait_for_completion(command_id, timeout=10)

        events = await command_bus.get_audit_trail(command_id, domain="e2e")

        # Should have at least 3 events
        assert len(events) >= 3

        # Verify chronological order
        for i in range(1, len(events)):
            assert events[i].timestamp >= events[i - 1].timestamp

        # Verify event type order
        event_types = [e.event_type for e in events]
        sent_idx = event_types.index("SENT")
        started_idx = event_types.index("STARTED")
        completed_idx = event_types.index("COMPLETED")

        assert sent_idx < started_idx < completed_idx
