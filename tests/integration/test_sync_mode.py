"""Integration smoke test for sync runtime components (S074/S087)."""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from uuid import uuid4

import pytest
from psycopg_pool import ConnectionPool

from commandbus import Command, CommandBus
from commandbus.handler import HandlerRegistry
from commandbus.models import CommandStatus, HandlerContext
from commandbus.sync import SyncCommandBus, SyncWorker


@pytest.mark.integration
@pytest.mark.asyncio
async def test_native_sync_round_trip(pool, cleanup_payments_domain) -> None:
    """Send and process a command using native sync components (S087)."""
    # Get connection info from async pool to create sync pool
    conninfo = pool.conninfo

    # Create sync pool for native sync components
    sync_pool: ConnectionPool[Any] = ConnectionPool(
        conninfo=conninfo,
        min_size=2,
        max_size=4,
        open=True,
    )

    try:
        # Create registry with sync handlers
        registry = HandlerRegistry()
        handled: list[str] = []

        @registry.sync_handler("payments", "SyncNativeCommand")
        def handle_sync_command(_command: Command, _ctx: HandlerContext) -> dict[str, str]:
            handled.append("ok")
            return {"status": "processed"}

        # Create native sync worker
        sync_worker = SyncWorker(
            pool=sync_pool,
            domain="payments",
            registry=registry,
            visibility_timeout=30,
            statement_timeout=25000,
        )

        # Create native sync command bus
        sync_bus = SyncCommandBus(sync_pool)

        # Run worker in background thread
        worker_thread = threading.Thread(
            target=sync_worker.run,
            kwargs={"concurrency": 1, "poll_interval": 0.1},
            daemon=True,
        )
        worker_thread.start()
        await asyncio.sleep(0.25)  # allow worker thread to start polling

        # Send command using sync bus (from main thread)
        command_id = uuid4()
        await asyncio.to_thread(
            sync_bus.send,
            domain="payments",
            command_type="SyncNativeCommand",
            command_id=command_id,
            data={"payload": "sync-native-test"},
        )

        # Wait for command to complete
        command_bus = CommandBus(pool)
        for _ in range(60):
            metadata = await command_bus.get_command("payments", command_id)
            if metadata and metadata.status == CommandStatus.COMPLETED:
                break
            await asyncio.sleep(0.25)
        else:  # pragma: no cover - defensive guard for CI flake
            raise AssertionError("Command did not complete in native sync mode")

        assert handled == ["ok"]
    finally:
        sync_worker.stop()
        worker_thread.join(timeout=5.0)
        sync_pool.close()
