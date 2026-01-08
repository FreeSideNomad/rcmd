"""Integration tests for FastAPI runtime manager dependencies (S072)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from commandbus.models import CommandStatus
from commandbus.sync import SyncCommandBus
from tests.e2e.app.config import ConfigStore, RuntimeConfig
from tests.e2e.app.models import TestCommandRepository
from tests.e2e.app.runtime import RuntimeManager


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_commands_respect_runtime(
    pool,
    worker_task,
    wait_for_completion,
    cleanup_db,
    monkeypatch,
) -> None:
    """Ensure runtime manager dispatches through sync wrappers when mode == sync."""
    store = ConfigStore()
    store.runtime = RuntimeConfig(mode="sync")
    await store.save_to_db(pool)

    sync_calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    class InstrumentedSyncCommandBus(SyncCommandBus):
        def send(self, *args, **kwargs):
            sync_calls.append(("send", args, kwargs))
            return super().send(*args, **kwargs)

    monkeypatch.setattr("tests.e2e.app.runtime.SyncCommandBus", InstrumentedSyncCommandBus)

    behavior_repo = TestCommandRepository(pool)
    manager = RuntimeManager(pool=pool, behavior_repo=behavior_repo)
    await manager.start(store.runtime)

    command_id = uuid4()
    await behavior_repo.create(command_id, behavior={}, payload={})

    try:
        await manager.command_bus.send(
            domain="e2e",
            command_type="TestCommand",
            command_id=command_id,
            data={"behavior": {}},
            max_attempts=3,
        )

        cmd = await wait_for_completion(command_id, timeout=15)
        assert cmd.status == CommandStatus.COMPLETED
        assert sync_calls, "SyncCommandBus should be invoked in sync mode"
    finally:
        await manager.shutdown()
        store.runtime = RuntimeConfig(mode="async")
        await store.save_to_db(pool)
        async with pool.connection() as conn:
            await conn.execute("DELETE FROM e2e.test_command WHERE command_id = %s", (command_id,))
