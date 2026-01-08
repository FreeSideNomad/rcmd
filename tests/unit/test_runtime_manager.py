from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from tests.e2e.app.config import RuntimeConfig
from tests.e2e.app.runtime import RuntimeManager


@pytest.fixture
def base_runtime_components(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Patch async components so RuntimeManager can run without a database."""
    events: dict[str, list[Any]] = {
        "async_bus_calls": [],
        "async_tsq_calls": [],
    }

    class FakeCommandBus:
        def __init__(self, pool: Any) -> None:
            self.pool = pool

        async def send(self, *args: Any, **kwargs: Any) -> str:
            events["async_bus_calls"].append(("send", args, kwargs))
            return "async-send"

        async def send_batch(self, *args: Any, **kwargs: Any) -> str:
            events["async_bus_calls"].append(("send_batch", args, kwargs))
            return "async-batch"

    class FakeTroubleshootingQueue:
        def __init__(self, pool: Any) -> None:
            self.pool = pool

        async def list_all_troubleshooting(self, *args: Any, **kwargs: Any) -> str:
            events["async_tsq_calls"].append(("list_all_troubleshooting", args, kwargs))
            return "tsq-list"

    class FakeProcessRepo:
        def __init__(self, pool: Any) -> None:
            self.pool = pool

    class FakeReportProcess:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr("tests.e2e.app.runtime.CommandBus", FakeCommandBus)
    monkeypatch.setattr("tests.e2e.app.runtime.TroubleshootingQueue", FakeTroubleshootingQueue)
    monkeypatch.setattr("tests.e2e.app.runtime.PostgresProcessRepository", FakeProcessRepo)
    monkeypatch.setattr("tests.e2e.app.runtime.StatementReportProcess", FakeReportProcess)
    return events


@pytest.mark.asyncio
async def test_async_mode_reuses_async_components(
    base_runtime_components: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Async mode should never instantiate sync wrappers."""

    # Fail the test if sync wrappers get constructed
    class FailSyncBus:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("SyncCommandBus should not be initialized for async mode")

    class FailSyncTqs:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError(
                "SyncTroubleshootingQueue should not be initialized for async mode"
            )

    monkeypatch.setattr("tests.e2e.app.runtime.SyncCommandBus", FailSyncBus)
    monkeypatch.setattr("tests.e2e.app.runtime.SyncTroubleshootingQueue", FailSyncTqs)

    manager = RuntimeManager(pool=object(), behavior_repo=object())
    await manager.start(RuntimeConfig(mode="async"))

    await manager.command_bus.send(
        domain="e2e",
        command_type="TestCommand",
        command_id=uuid4(),
    )
    await manager.troubleshooting_queue.list_all_troubleshooting()

    assert base_runtime_components["async_bus_calls"]
    assert base_runtime_components["async_tsq_calls"]


@pytest.mark.asyncio
async def test_sync_mode_routes_through_sync_wrappers(
    base_runtime_components: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sync mode should execute via SyncCommandBus + asyncio.to_thread."""
    sync_bus_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    sync_tsq_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    class FakeSyncRuntime:
        def shutdown(self) -> None:
            return None

    class FakeSyncBus:
        def __init__(self, *, bus: Any, runtime: Any) -> None:
            self.bus = bus
            self.runtime = runtime

        def send(self, *args: Any, **kwargs: Any) -> str:
            sync_bus_calls.append(("send", args, kwargs))
            return "sync-send"

    class FakeSyncTqs:
        def __init__(self, *, queue: Any, runtime: Any) -> None:
            self.queue = queue
            self.runtime = runtime

        def list_all_troubleshooting(self, *args: Any, **kwargs: Any) -> str:
            sync_tsq_calls.append(("list", args, kwargs))
            return "sync-tsq"

    async def fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr("tests.e2e.app.runtime.SyncRuntime", FakeSyncRuntime)
    monkeypatch.setattr("tests.e2e.app.runtime.SyncCommandBus", FakeSyncBus)
    monkeypatch.setattr("tests.e2e.app.runtime.SyncTroubleshootingQueue", FakeSyncTqs)
    monkeypatch.setattr("tests.e2e.app.runtime.asyncio.to_thread", fake_to_thread)

    manager = RuntimeManager(pool=object(), behavior_repo=object())
    await manager.start(RuntimeConfig(mode="sync"))

    result = await manager.command_bus.send(
        domain="e2e",
        command_type="TestCommand",
        command_id=uuid4(),
    )
    tsq_result = await manager.troubleshooting_queue.list_all_troubleshooting()

    assert result == "sync-send"
    assert tsq_result == "sync-tsq"
    assert sync_bus_calls
    assert sync_tsq_calls
    # Async components should not record direct usage in sync mode
    assert not base_runtime_components["async_bus_calls"]
    assert not base_runtime_components["async_tsq_calls"]


@pytest.mark.asyncio
async def test_shutdown_clears_sync_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shutdown should stop the SyncRuntime and drop adapters."""
    shutdown_called = False

    class FakeSyncRuntime:
        def shutdown(self) -> None:
            nonlocal shutdown_called
            shutdown_called = True

    class FakeSyncBus:
        def __init__(self, *, bus: Any, runtime: Any) -> None:
            self.runtime = runtime

        def send(self, *args: Any, **kwargs: Any) -> str:
            return "sync"

    class FakeSyncTqs:
        def __init__(self, *, queue: Any, runtime: Any) -> None:
            self.runtime = runtime

        def list_all_troubleshooting(self, *args: Any, **kwargs: Any) -> str:
            return "sync-tsq"

    class FakeCommandBus:
        def __init__(self, pool: Any) -> None:
            self.pool = pool

        async def send(self, *args: Any, **kwargs: Any) -> str:
            return "async"

    class FakeTroubleshootingQueue:
        def __init__(self, pool: Any) -> None:
            self.pool = pool

        async def list_all_troubleshooting(self, *args: Any, **kwargs: Any) -> str:
            return "async-tsq"

    class FakeProcessRepo:
        def __init__(self, pool: Any) -> None:
            self.pool = pool

    class FakeReportProcess:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    async def fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr("tests.e2e.app.runtime.CommandBus", FakeCommandBus)
    monkeypatch.setattr("tests.e2e.app.runtime.TroubleshootingQueue", FakeTroubleshootingQueue)
    monkeypatch.setattr("tests.e2e.app.runtime.PostgresProcessRepository", FakeProcessRepo)
    monkeypatch.setattr("tests.e2e.app.runtime.StatementReportProcess", FakeReportProcess)
    monkeypatch.setattr("tests.e2e.app.runtime.SyncRuntime", FakeSyncRuntime)
    monkeypatch.setattr("tests.e2e.app.runtime.SyncCommandBus", FakeSyncBus)
    monkeypatch.setattr("tests.e2e.app.runtime.SyncTroubleshootingQueue", FakeSyncTqs)
    monkeypatch.setattr("tests.e2e.app.runtime.asyncio.to_thread", fake_to_thread)

    manager = RuntimeManager(pool=object(), behavior_repo=object())
    await manager.start(RuntimeConfig(mode="sync"))

    await manager.shutdown()

    assert shutdown_called
    with pytest.raises(AssertionError):
        _ = manager.command_bus
