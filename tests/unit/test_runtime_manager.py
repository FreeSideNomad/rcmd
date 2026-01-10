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
    """Async mode should never instantiate sync components."""

    # Fail the test if sync components get constructed
    class FailSyncBus:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("SyncCommandBus should not be initialized for async mode")

    monkeypatch.setattr("tests.e2e.app.runtime.SyncCommandBus", FailSyncBus)

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
async def test_sync_mode_routes_through_native_sync_bus(
    base_runtime_components: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sync mode should execute command bus ops via native SyncCommandBus."""
    sync_bus_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    class FakeConnectionPool:
        """Fake sync connection pool."""

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def close(self) -> None:
            pass

    class FakeSyncBus:
        def __init__(self, pool: Any) -> None:
            self.pool = pool

        def send(self, *args: Any, **kwargs: Any) -> str:
            sync_bus_calls.append(("send", args, kwargs))
            return "sync-send"

    async def fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr("tests.e2e.app.runtime.ConnectionPool", FakeConnectionPool)
    monkeypatch.setattr("tests.e2e.app.runtime.SyncCommandBus", FakeSyncBus)
    monkeypatch.setattr("tests.e2e.app.runtime.asyncio.to_thread", fake_to_thread)

    manager = RuntimeManager(pool=object(), behavior_repo=object())
    await manager.start(RuntimeConfig(mode="sync"))

    result = await manager.command_bus.send(
        domain="e2e",
        command_type="TestCommand",
        command_id=uuid4(),
    )

    assert result == "sync-send"
    assert sync_bus_calls
    # Async bus should not record direct usage in sync mode
    assert not base_runtime_components["async_bus_calls"]


@pytest.mark.asyncio
async def test_sync_mode_troubleshooting_uses_async(
    base_runtime_components: dict[str, list[Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Troubleshooting queue should use async version even in sync mode."""

    class FakeConnectionPool:
        """Fake sync connection pool."""

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def close(self) -> None:
            pass

    class FakeSyncBus:
        def __init__(self, pool: Any) -> None:
            self.pool = pool

        def send(self, *args: Any, **kwargs: Any) -> str:
            return "sync-send"

    monkeypatch.setattr("tests.e2e.app.runtime.ConnectionPool", FakeConnectionPool)
    monkeypatch.setattr("tests.e2e.app.runtime.SyncCommandBus", FakeSyncBus)

    manager = RuntimeManager(pool=object(), behavior_repo=object())
    await manager.start(RuntimeConfig(mode="sync"))

    await manager.troubleshooting_queue.list_all_troubleshooting()

    # TSQ uses async version in both modes (no native sync version)
    assert base_runtime_components["async_tsq_calls"]


@pytest.mark.asyncio
async def test_shutdown_closes_sync_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shutdown should close the sync connection pool."""
    pool_closed = False

    class FakeConnectionPool:
        """Fake sync connection pool."""

        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def close(self) -> None:
            nonlocal pool_closed
            pool_closed = True

    class FakeSyncBus:
        def __init__(self, pool: Any) -> None:
            self.pool = pool

        def send(self, *args: Any, **kwargs: Any) -> str:
            return "sync"

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
    monkeypatch.setattr("tests.e2e.app.runtime.ConnectionPool", FakeConnectionPool)
    monkeypatch.setattr("tests.e2e.app.runtime.SyncCommandBus", FakeSyncBus)
    monkeypatch.setattr("tests.e2e.app.runtime.asyncio.to_thread", fake_to_thread)

    manager = RuntimeManager(pool=object(), behavior_repo=object())
    await manager.start(RuntimeConfig(mode="sync"))

    await manager.shutdown()

    assert pool_closed
    with pytest.raises(AssertionError):
        _ = manager.command_bus
