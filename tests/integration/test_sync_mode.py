"""Integration smoke test for sync runtime components (S074)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from commandbus import CommandBus
from commandbus.handler import HandlerRegistry
from commandbus.models import CommandStatus, HandlerContext
from commandbus.sync import SyncCommandBus, SyncRuntime, SyncWorker
from commandbus.worker import Worker


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Wrapper-based SyncCommandBus replaced by native sync - to be updated in S087"
)
async def test_sync_runtime_round_trip(pool, cleanup_payments_domain) -> None:
    """Send and process a command entirely through sync wrappers."""
    registry = HandlerRegistry()
    handled: list[str] = []

    @registry.handler("payments", "SyncRuntimeCommand")
    async def handle_sync_command(_command, _ctx: HandlerContext) -> dict[str, str]:
        handled.append("ok")
        return {"status": "processed"}

    base_worker = Worker(
        pool,
        domain="payments",
        registry=registry,
        visibility_timeout=5,
    )
    runtime = SyncRuntime()
    sync_worker = SyncWorker(worker=base_worker, runtime=runtime, thread_pool_size=2)
    sync_bus = SyncCommandBus(bus=CommandBus(pool), runtime=runtime)

    try:
        sync_worker.run(block=False, concurrency=1, poll_interval=0.1, use_notify=False)
        await asyncio.sleep(0.25)  # allow worker thread to start polling

        command_id = uuid4()
        await asyncio.to_thread(
            sync_bus.send,
            domain="payments",
            command_type="SyncRuntimeCommand",
            command_id=command_id,
            data={"payload": "sync-test"},
        )
        await asyncio.sleep(0.25)

        command_bus = CommandBus(pool)
        for _ in range(60):
            metadata = await command_bus.get_command("payments", command_id)
            if metadata and metadata.status == CommandStatus.COMPLETED:
                break
            await asyncio.sleep(0.25)
        else:  # pragma: no cover - defensive guard for CI flake
            raise AssertionError("Command did not complete in sync mode")

        assert handled == ["ok"]
    finally:
        sync_worker.stop()
        sync_worker.shutdown()
        runtime.shutdown()
