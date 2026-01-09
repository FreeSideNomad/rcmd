from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from tests.e2e.app import worker as worker_module
from tests.e2e.app.config import RetryConfig, RuntimeConfig, WorkerConfig


class FakePool:
    def __init__(self) -> None:
        self.closed = False
        self.min_size: int | None = None
        self.max_size: int | None = None

    async def close(self) -> None:
        self.closed = True


class FakeRouter:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.run_calls: list[dict[str, Any]] = []
        self.stop_calls: int = 0

    async def run(self, **kwargs: Any) -> None:
        self.run_calls.append(kwargs)

    async def stop(self, *args: Any, **kwargs: Any) -> None:
        self.stop_calls += 1


class FakeWorker:
    def __init__(self) -> None:
        self.run_calls: list[dict[str, Any]] = []
        self.stop_calls: int = 0

    async def run(self, **kwargs: Any) -> None:
        self.run_calls.append(kwargs)

    async def stop(self, *args: Any, **kwargs: Any) -> None:
        self.stop_calls += 1


@pytest.mark.asyncio
async def test_async_mode_default(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    pool = FakePool()

    async def fake_create_pool(*, min_size: int, max_size: int) -> FakePool:
        pool.min_size = min_size
        pool.max_size = max_size
        return pool

    monkeypatch.setattr(worker_module, "create_pool", fake_create_pool)
    monkeypatch.setattr(worker_module, "create_registry", lambda _pool: "registry")
    monkeypatch.setattr(worker_module, "CommandBus", lambda _pool: "bus")
    monkeypatch.setattr(worker_module, "PostgresProcessRepository", lambda _pool: "repo")
    monkeypatch.setattr(worker_module, "TestCommandRepository", lambda _pool: "behavior_repo")

    fake_router = FakeRouter()
    monkeypatch.setattr(worker_module, "ProcessReplyRouter", lambda **kwargs: fake_router)

    workers: list[FakeWorker] = []

    def _create_worker(*_args: Any, **_kwargs: Any) -> FakeWorker:
        worker = FakeWorker()
        workers.append(worker)
        return worker

    monkeypatch.setattr(worker_module, "create_worker", _create_worker)
    monkeypatch.setattr(
        worker_module,
        "StatementReportProcess",
        lambda **kwargs: SimpleNamespace(process_type="StatementReport", kwargs=kwargs),
    )

    worker_cfg = WorkerConfig(concurrency=3, visibility_timeout=45, poll_interval=2.5)
    runtime_cfg = RuntimeConfig(mode="async")
    retry_cfg = RetryConfig(max_attempts=5, backoff_schedule=[1, 2, 4])
    store = SimpleNamespace(worker=worker_cfg, runtime=runtime_cfg, retry=retry_cfg)

    pool_cap = 200

    async def fake_load_runtime_settings() -> tuple[SimpleNamespace, int]:
        return store, pool_cap

    monkeypatch.setattr(worker_module, "_load_runtime_settings", fake_load_runtime_settings)

    shutdown_event = asyncio.Event()
    shutdown_event.set()

    await worker_module.run_worker(shutdown_event=shutdown_event)

    assert pool.closed
    expected_min, expected_max, expected_concurrency = worker_module._calculate_pool_plan(
        worker_cfg, pool_cap
    )
    assert pool.min_size == expected_min
    assert pool.max_size == expected_max
    assert workers
    for worker in workers:
        assert worker.run_calls
        assert worker.run_calls[0]["concurrency"] == expected_concurrency
    assert len(workers) == 2
    for call in workers[0].run_calls + workers[1].run_calls:
        assert call["concurrency"] == expected_concurrency
        assert call["poll_interval"] == worker_cfg.poll_interval
    assert fake_router.run_calls
    assert fake_router.stop_calls == 1
    assert all(worker.stop_calls == 1 for worker in workers)
    assert any("Runtime mode: async" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_sync_mode_lifecycle(  # noqa: PLR0915
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    pool = FakePool()

    async def fake_create_pool(*, min_size: int, max_size: int) -> FakePool:
        pool.min_size = min_size
        pool.max_size = max_size
        return pool

    monkeypatch.setattr(worker_module, "create_pool", fake_create_pool)
    monkeypatch.setattr(worker_module, "create_registry", lambda _pool: "registry")
    monkeypatch.setattr(worker_module, "CommandBus", lambda _pool: "bus")
    monkeypatch.setattr(worker_module, "PostgresProcessRepository", lambda _pool: "repo")
    monkeypatch.setattr(worker_module, "TestCommandRepository", lambda _pool: "behavior_repo")
    monkeypatch.setattr(
        worker_module,
        "StatementReportProcess",
        lambda **kwargs: SimpleNamespace(process_type="StatementReport", kwargs=kwargs),
    )

    base_workers: list[FakeWorker] = []

    def _create_worker(*_args: Any, **_kwargs: Any) -> FakeWorker:
        worker = FakeWorker()
        base_workers.append(worker)
        return worker

    monkeypatch.setattr(worker_module, "create_worker", _create_worker)

    worker_cfg = WorkerConfig(concurrency=2, visibility_timeout=30, poll_interval=1.0)
    runtime_cfg = RuntimeConfig(mode="sync", thread_pool_size=6)
    retry_cfg = RetryConfig(max_attempts=3, backoff_schedule=[2])
    store = SimpleNamespace(worker=worker_cfg, runtime=runtime_cfg, retry=retry_cfg)

    pool_cap = 150

    async def fake_load_runtime_settings() -> tuple[SimpleNamespace, int]:
        return store, pool_cap

    monkeypatch.setattr(worker_module, "_load_runtime_settings", fake_load_runtime_settings)

    expected_min, expected_max, expected_concurrency = worker_module._calculate_pool_plan(
        worker_cfg, pool_cap
    )

    created_runtime: list[FakeSyncRuntime] = []

    class FakeSyncRuntime:
        def __init__(self) -> None:
            self.shutdown_called = False
            created_runtime.append(self)

        def shutdown(self) -> None:
            self.shutdown_called = True

    class FakeSyncWorkerWrapper:
        instances: ClassVar[list[FakeSyncWorkerWrapper]] = []

        def __init__(
            self,
            *,
            worker: FakeWorker,
            runtime: FakeSyncRuntime,
            thread_pool_size: int | None = None,
        ) -> None:
            self.worker = worker
            self.runtime = runtime
            self.thread_pool_size = thread_pool_size
            self.run_calls: int = 0
            self.run_kwargs: list[dict[str, Any]] = []
            self.stop_calls: int = 0
            self.shutdown_calls: int = 0
            FakeSyncWorkerWrapper.instances.append(self)

        def run(self, **_kwargs: Any) -> None:
            self.run_calls += 1
            self.run_kwargs.append(_kwargs)

        def stop(self) -> None:
            self.stop_calls += 1

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    created_sync_router: list[FakeSyncRouter] = []

    class FakeSyncRouter:
        def __init__(self, **_kwargs: Any) -> None:
            self.run_calls = 0
            self.stop_calls = 0
            self.shutdown_calls = 0

        def run(self, **_kwargs: Any) -> None:
            self.run_calls += 1

        def stop(self) -> None:
            self.stop_calls += 1

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    monkeypatch.setattr(worker_module, "SyncRuntime", FakeSyncRuntime)
    monkeypatch.setattr(worker_module, "SyncWorker", FakeSyncWorkerWrapper)

    def _create_sync_router(**kwargs: Any) -> FakeSyncRouter:
        router = FakeSyncRouter(**kwargs)
        created_sync_router.append(router)
        return router

    monkeypatch.setattr(worker_module, "SyncProcessReplyRouter", _create_sync_router)
    monkeypatch.setattr(worker_module, "ProcessReplyRouter", lambda **kwargs: FakeSyncRouter())

    async def fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(worker_module.asyncio, "to_thread", fake_to_thread)

    shutdown_event = asyncio.Event()
    shutdown_event.set()

    await worker_module.run_worker(shutdown_event=shutdown_event)

    assert pool.closed
    assert created_runtime and created_runtime[0].shutdown_called
    assert pool.min_size == expected_min
    assert pool.max_size == expected_max
    assert len(FakeSyncWorkerWrapper.instances) == 2
    assert all(instance.run_calls == 1 for instance in FakeSyncWorkerWrapper.instances)
    for instance in FakeSyncWorkerWrapper.instances:
        assert instance.run_kwargs
        assert instance.run_kwargs[0]["concurrency"] == min(expected_concurrency, 2)
    assert all(instance.stop_calls == 1 for instance in FakeSyncWorkerWrapper.instances)
    assert all(instance.shutdown_calls == 1 for instance in FakeSyncWorkerWrapper.instances)
    assert created_sync_router and created_sync_router[0].stop_calls == 1
    assert created_sync_router[0].shutdown_calls == 1
    assert any("Runtime mode: sync" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_sync_mode_concurrency_cap_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    pool = FakePool()

    async def fake_create_pool(*, min_size: int, max_size: int) -> FakePool:
        pool.min_size = min_size
        pool.max_size = max_size
        return pool

    monkeypatch.setattr(worker_module, "create_pool", fake_create_pool)
    monkeypatch.setattr(worker_module, "create_registry", lambda _pool: "registry")
    monkeypatch.setattr(worker_module, "CommandBus", lambda _pool: "bus")
    monkeypatch.setattr(worker_module, "PostgresProcessRepository", lambda _pool: "repo")
    monkeypatch.setattr(worker_module, "TestCommandRepository", lambda _pool: "behavior_repo")
    monkeypatch.setattr(
        worker_module,
        "StatementReportProcess",
        lambda **kwargs: SimpleNamespace(process_type="StatementReport", kwargs=kwargs),
    )

    worker_cfg = WorkerConfig(concurrency=10, visibility_timeout=30, poll_interval=1.0)
    runtime_cfg = RuntimeConfig(mode="sync", thread_pool_size=4)
    retry_cfg = RetryConfig()
    store = SimpleNamespace(worker=worker_cfg, runtime=runtime_cfg, retry=retry_cfg)

    pool_cap = 100

    async def fake_load_runtime_settings() -> tuple[SimpleNamespace, int]:
        return store, pool_cap

    monkeypatch.setattr(worker_module, "_load_runtime_settings", fake_load_runtime_settings)

    class InspectableSyncWorker:
        instances: ClassVar[list[dict[str, Any]]] = []

        def __init__(
            self, *, worker: FakeWorker, runtime: Any, thread_pool_size: int | None = None
        ) -> None:
            self.worker = worker
            self.runtime = runtime
            self.thread_pool_size = thread_pool_size

        def run(self, **kwargs: Any) -> None:
            InspectableSyncWorker.instances.append(kwargs)

        def stop(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

    class StubSyncRouter:
        def run(self, **_kwargs: Any) -> None:
            return None

        def stop(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr(worker_module, "SyncWorker", InspectableSyncWorker)
    monkeypatch.setattr(worker_module, "SyncProcessReplyRouter", lambda **_: StubSyncRouter())
    monkeypatch.setattr(worker_module, "ProcessReplyRouter", lambda **_: StubSyncRouter())

    shutdown_event = asyncio.Event()
    shutdown_event.set()

    await worker_module.run_worker(shutdown_event=shutdown_event)

    assert InspectableSyncWorker.instances
    for kwargs in InspectableSyncWorker.instances:
        assert kwargs["concurrency"] == 2
    assert any("forcing concurrency to 2" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_sync_thread_pool_override(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = FakePool()

    async def fake_create_pool(*, min_size: int, max_size: int) -> FakePool:
        pool.min_size = min_size
        pool.max_size = max_size
        return pool

    monkeypatch.setattr(worker_module, "create_pool", fake_create_pool)
    monkeypatch.setattr(worker_module, "create_registry", lambda _pool: "registry")
    monkeypatch.setattr(worker_module, "CommandBus", lambda _pool: "bus")
    monkeypatch.setattr(worker_module, "PostgresProcessRepository", lambda _pool: "repo")
    monkeypatch.setattr(worker_module, "TestCommandRepository", lambda _pool: "behavior_repo")
    monkeypatch.setattr(
        worker_module,
        "StatementReportProcess",
        lambda **kwargs: SimpleNamespace(process_type="StatementReport", kwargs=kwargs),
    )

    monkeypatch.setattr(worker_module, "create_worker", lambda *args, **kwargs: FakeWorker())

    worker_cfg = WorkerConfig(concurrency=1, visibility_timeout=30, poll_interval=1.0)
    runtime_cfg = RuntimeConfig(mode="sync", thread_pool_size=12)
    retry_cfg = RetryConfig()
    store = SimpleNamespace(worker=worker_cfg, runtime=runtime_cfg, retry=retry_cfg)

    pool_cap = 80

    async def fake_load_runtime_settings() -> tuple[SimpleNamespace, int]:
        return store, pool_cap

    monkeypatch.setattr(worker_module, "_load_runtime_settings", fake_load_runtime_settings)

    class InspectableSyncWorker:
        instances: ClassVar[list[int | None]] = []

        def __init__(
            self, *, worker: FakeWorker, runtime: Any, thread_pool_size: int | None = None
        ) -> None:
            InspectableSyncWorker.instances.append(thread_pool_size)

        def run(self, **_kwargs: Any) -> None:
            return None

        def stop(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

    class InspectableRouter:
        def __init__(self, **_kwargs: Any) -> None:
            return None

        def run(self, **_kwargs: Any) -> None:
            return None

        def stop(self) -> None:
            return None

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr(
        worker_module, "SyncRuntime", lambda: SimpleNamespace(shutdown=lambda: None)
    )
    monkeypatch.setattr(worker_module, "SyncWorker", InspectableSyncWorker)
    monkeypatch.setattr(
        worker_module, "SyncProcessReplyRouter", lambda **kwargs: InspectableRouter(**kwargs)
    )
    monkeypatch.setattr(
        worker_module.asyncio, "to_thread", lambda func, *args, **kwargs: asyncio.sleep(0)
    )

    shutdown_event = asyncio.Event()
    shutdown_event.set()

    await worker_module.run_worker(shutdown_event=shutdown_event)

    assert InspectableSyncWorker.instances == [
        runtime_cfg.thread_pool_size,
        runtime_cfg.thread_pool_size,
    ]
    assert pool.closed


def test_calculate_pool_plan_scales_with_concurrency() -> None:
    worker_cfg = WorkerConfig(concurrency=10)
    pool_cap = 500
    min_size, max_size, effective = worker_module._calculate_pool_plan(worker_cfg, pool_cap)
    assert min_size == worker_module.POOL_MIN_SIZE
    assert max_size > worker_module.POOL_HEADROOM
    assert effective == worker_cfg.concurrency


def test_calculate_pool_plan_handles_zero_concurrency() -> None:
    worker_cfg = WorkerConfig(concurrency=0)
    _, _, effective = worker_module._calculate_pool_plan(worker_cfg, 100)
    assert effective == 1


def test_calculate_pool_plan_caps_when_pool_small() -> None:
    worker_cfg = WorkerConfig(concurrency=50)
    pool_cap = worker_module.POOL_HEADROOM + worker_module.LISTEN_CONNECTIONS + 20
    _, max_size, effective = worker_module._calculate_pool_plan(worker_cfg, pool_cap)
    assert max_size == pool_cap
    assert effective < worker_cfg.concurrency
    assert effective >= 1
