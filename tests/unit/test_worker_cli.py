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
    """Test native sync mode worker lifecycle."""
    caplog.set_level(logging.INFO)

    pool = FakePool()

    async def fake_create_pool(*, min_size: int, max_size: int) -> FakePool:
        pool.min_size = min_size
        pool.max_size = max_size
        return pool

    monkeypatch.setattr(worker_module, "create_pool", fake_create_pool)
    monkeypatch.setattr(worker_module, "create_registry", lambda _pool: "registry")
    monkeypatch.setattr(worker_module, "create_sync_registry", lambda _pool: "sync_registry")
    monkeypatch.setattr(worker_module, "CommandBus", lambda _pool: "bus")
    monkeypatch.setattr(worker_module, "PostgresProcessRepository", lambda _pool: "repo")
    monkeypatch.setattr(worker_module, "SyncProcessRepository", lambda _pool: "sync_repo")
    monkeypatch.setattr(worker_module, "TestCommandRepository", lambda _pool: "behavior_repo")
    monkeypatch.setattr(
        worker_module,
        "StatementReportProcess",
        lambda **kwargs: SimpleNamespace(process_type="StatementReport", kwargs=kwargs),
    )

    worker_cfg = WorkerConfig(concurrency=2, visibility_timeout=30, poll_interval=1.0)
    runtime_cfg = RuntimeConfig(mode="sync", thread_pool_size=6)
    retry_cfg = RetryConfig(max_attempts=3, backoff_schedule=[2])
    store = SimpleNamespace(worker=worker_cfg, runtime=runtime_cfg, retry=retry_cfg)

    pool_cap = 150

    async def fake_load_runtime_settings() -> tuple[SimpleNamespace, int]:
        return store, pool_cap

    monkeypatch.setattr(worker_module, "_load_runtime_settings", fake_load_runtime_settings)

    # For sync mode, use the sync pool plan calculation (different sizing requirements)
    expected_min, expected_max, expected_concurrency = worker_module._calculate_sync_pool_plan(
        worker_cfg, pool_cap
    )

    # Track sync pool creation
    created_sync_pools: list[SimpleNamespace] = []

    class FakeSyncPool:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.closed = False
            created_sync_pools.append(self)  # type: ignore[arg-type]

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(worker_module, "ConnectionPool", FakeSyncPool)

    class FakeNativeSyncWorker:
        instances: ClassVar[list[FakeNativeSyncWorker]] = []

        def __init__(
            self,
            pool: Any,
            domain: str,
            registry: Any,
            *,
            visibility_timeout: int = 30,
            retry_policy: Any = None,
        ) -> None:
            self.pool = pool
            self.domain = domain
            self.registry = registry
            self.visibility_timeout = visibility_timeout
            self.retry_policy = retry_policy
            self.run_calls: int = 0
            self.run_kwargs: list[dict[str, Any]] = []
            self.stop_calls: int = 0
            FakeNativeSyncWorker.instances.append(self)

        def run(self, **kwargs: Any) -> None:
            self.run_calls += 1
            self.run_kwargs.append(kwargs)

        def stop(self, timeout: float | None = None) -> None:
            self.stop_calls += 1

    created_sync_router: list[FakeNativeSyncRouter] = []

    class FakeNativeSyncRouter:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self._reply_queue = kwargs.get("reply_queue")
            self.run_calls = 0
            self.stop_calls = 0
            created_sync_router.append(self)

        def run(self, **_kwargs: Any) -> None:
            self.run_calls += 1

        def stop(self, timeout: float | None = None) -> None:
            self.stop_calls += 1

    FakeNativeSyncWorker.instances = []  # Reset class-level state
    monkeypatch.setattr(worker_module, "SyncWorker", FakeNativeSyncWorker)
    monkeypatch.setattr(worker_module, "SyncProcessReplyRouter", FakeNativeSyncRouter)
    monkeypatch.setattr(worker_module, "ProcessReplyRouter", lambda **kwargs: FakeRouter())

    async def fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(worker_module.asyncio, "to_thread", fake_to_thread)

    shutdown_event = asyncio.Event()
    shutdown_event.set()

    await worker_module.run_worker(shutdown_event=shutdown_event)

    assert pool.closed
    # In sync mode, the async pool is sized smaller (just for handlers that use it)
    assert pool.min_size == worker_module.POOL_MIN_SIZE
    async_pool_max = max(worker_module.POOL_MIN_SIZE, expected_concurrency)
    assert pool.max_size == async_pool_max

    # Check sync pool was created with correct sizing and closed
    assert len(created_sync_pools) == 1
    sync_pool_params = created_sync_pools[0].kwargs
    assert sync_pool_params["min_size"] == expected_min
    assert sync_pool_params["max_size"] == expected_max
    assert created_sync_pools[0].closed

    # Check native sync workers were created
    assert len(FakeNativeSyncWorker.instances) == 2
    assert all(instance.run_calls == 1 for instance in FakeNativeSyncWorker.instances)
    for instance in FakeNativeSyncWorker.instances:
        assert instance.run_kwargs
        assert instance.run_kwargs[0]["concurrency"] == expected_concurrency
    assert all(instance.stop_calls == 1 for instance in FakeNativeSyncWorker.instances)

    # Check native sync router
    assert created_sync_router and created_sync_router[0].stop_calls == 1
    assert any("Runtime mode: sync" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_sync_mode_uses_native_components(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that sync mode uses native SyncWorker with proper parameters."""
    caplog.set_level(logging.INFO)

    pool = FakePool()

    async def fake_create_pool(*, min_size: int, max_size: int) -> FakePool:
        pool.min_size = min_size
        pool.max_size = max_size
        return pool

    monkeypatch.setattr(worker_module, "create_pool", fake_create_pool)
    monkeypatch.setattr(worker_module, "create_registry", lambda _pool: "registry")
    monkeypatch.setattr(worker_module, "create_sync_registry", lambda _pool: "sync_registry")
    monkeypatch.setattr(worker_module, "CommandBus", lambda _pool: "bus")
    monkeypatch.setattr(worker_module, "PostgresProcessRepository", lambda _pool: "repo")
    monkeypatch.setattr(worker_module, "SyncProcessRepository", lambda _pool: "sync_repo")
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

    pool_cap = 500  # Large enough to support concurrency=10

    async def fake_load_runtime_settings() -> tuple[SimpleNamespace, int]:
        return store, pool_cap

    monkeypatch.setattr(worker_module, "_load_runtime_settings", fake_load_runtime_settings)

    _expected_min, _expected_max, expected_concurrency = worker_module._calculate_pool_plan(
        worker_cfg, pool_cap
    )

    # Track sync pool creation
    class FakeSyncPool:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.closed = False

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(worker_module, "ConnectionPool", FakeSyncPool)

    class InspectableSyncWorker:
        instances: ClassVar[list[InspectableSyncWorker]] = []

        def __init__(
            self,
            pool: Any,
            domain: str,
            registry: Any,
            *,
            visibility_timeout: int = 30,
            retry_policy: Any = None,
        ) -> None:
            self.pool = pool
            self.domain = domain
            self.registry = registry
            self.visibility_timeout = visibility_timeout
            self.retry_policy = retry_policy
            self.run_kwargs: list[dict[str, Any]] = []
            InspectableSyncWorker.instances.append(self)

        def run(self, **kwargs: Any) -> None:
            self.run_kwargs.append(kwargs)

        def stop(self, timeout: float | None = None) -> None:
            return None

    class StubSyncRouter:
        _reply_queue: str | None = None

        def __init__(self, **kwargs: Any) -> None:
            self._reply_queue = kwargs.get("reply_queue")

        def run(self, **_kwargs: Any) -> None:
            return None

        def stop(self, timeout: float | None = None) -> None:
            return None

    InspectableSyncWorker.instances = []
    monkeypatch.setattr(worker_module, "SyncWorker", InspectableSyncWorker)
    monkeypatch.setattr(worker_module, "SyncProcessReplyRouter", StubSyncRouter)
    monkeypatch.setattr(worker_module, "ProcessReplyRouter", lambda **_: StubSyncRouter())

    async def fake_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    monkeypatch.setattr(worker_module.asyncio, "to_thread", fake_to_thread)

    shutdown_event = asyncio.Event()
    shutdown_event.set()

    await worker_module.run_worker(shutdown_event=shutdown_event)

    # Native sync workers should use full concurrency (no cap)
    assert InspectableSyncWorker.instances
    for worker in InspectableSyncWorker.instances:
        assert worker.run_kwargs
        assert worker.run_kwargs[0]["concurrency"] == expected_concurrency
        assert worker.domain in ("e2e", "reporting")
        assert worker.registry == "sync_registry"


@pytest.mark.asyncio
async def test_sync_pool_created_with_correct_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that sync mode creates ConnectionPool with correct min/max size."""
    pool = FakePool()

    async def fake_create_pool(*, min_size: int, max_size: int) -> FakePool:
        pool.min_size = min_size
        pool.max_size = max_size
        return pool

    monkeypatch.setattr(worker_module, "create_pool", fake_create_pool)
    monkeypatch.setattr(worker_module, "create_registry", lambda _pool: "registry")
    monkeypatch.setattr(worker_module, "create_sync_registry", lambda _pool: "sync_registry")
    monkeypatch.setattr(worker_module, "CommandBus", lambda _pool: "bus")
    monkeypatch.setattr(worker_module, "PostgresProcessRepository", lambda _pool: "repo")
    monkeypatch.setattr(worker_module, "SyncProcessRepository", lambda _pool: "sync_repo")
    monkeypatch.setattr(worker_module, "TestCommandRepository", lambda _pool: "behavior_repo")
    monkeypatch.setattr(
        worker_module,
        "StatementReportProcess",
        lambda **kwargs: SimpleNamespace(process_type="StatementReport", kwargs=kwargs),
    )

    worker_cfg = WorkerConfig(concurrency=1, visibility_timeout=30, poll_interval=1.0)
    runtime_cfg = RuntimeConfig(mode="sync", thread_pool_size=12)
    retry_cfg = RetryConfig()
    store = SimpleNamespace(worker=worker_cfg, runtime=runtime_cfg, retry=retry_cfg)

    pool_cap = 80

    async def fake_load_runtime_settings() -> tuple[SimpleNamespace, int]:
        return store, pool_cap

    monkeypatch.setattr(worker_module, "_load_runtime_settings", fake_load_runtime_settings)

    # For sync mode, use the sync pool plan calculation
    expected_min, expected_max, _ = worker_module._calculate_sync_pool_plan(worker_cfg, pool_cap)

    # Track sync pool creation parameters
    created_sync_pools: list[dict[str, Any]] = []

    class InspectableSyncPool:
        def __init__(self, **kwargs: Any) -> None:
            created_sync_pools.append(kwargs)
            self.closed = False

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(worker_module, "ConnectionPool", InspectableSyncPool)

    class StubSyncWorker:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def run(self, **_kwargs: Any) -> None:
            return None

        def stop(self, timeout: float | None = None) -> None:
            return None

    class StubSyncRouter:
        _reply_queue: str | None = None

        def __init__(self, **kwargs: Any) -> None:
            self._reply_queue = kwargs.get("reply_queue")

        def run(self, **_kwargs: Any) -> None:
            return None

        def stop(self, timeout: float | None = None) -> None:
            return None

    monkeypatch.setattr(worker_module, "SyncWorker", StubSyncWorker)
    monkeypatch.setattr(worker_module, "SyncProcessReplyRouter", StubSyncRouter)
    monkeypatch.setattr(
        worker_module.asyncio, "to_thread", lambda func, *args, **kwargs: asyncio.sleep(0)
    )

    shutdown_event = asyncio.Event()
    shutdown_event.set()

    await worker_module.run_worker(shutdown_event=shutdown_event)

    # Verify sync pool was created with expected parameters
    assert len(created_sync_pools) == 1
    assert created_sync_pools[0]["min_size"] == expected_min
    assert created_sync_pools[0]["max_size"] == expected_max
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


def test_calculate_sync_pool_plan_sizes_for_all_threads() -> None:
    """Sync pool must accommodate all concurrent threads (workers + router)."""
    worker_cfg = WorkerConfig(concurrency=4)
    pool_cap = 100
    min_size, max_size, effective = worker_module._calculate_sync_pool_plan(worker_cfg, pool_cap)
    # Each service (workers + router) needs `concurrency` connections plus overhead.
    total_services = len(worker_module.WORKER_DOMAINS) + 1
    expected_max = total_services * 4 + worker_module.SYNC_POOL_OVERHEAD
    assert max_size == expected_max
    assert effective == 4
    assert min_size >= worker_module.POOL_MIN_SIZE


def test_calculate_sync_pool_plan_caps_concurrency_when_pool_limited() -> None:
    """When pool_cap is small, reduce concurrency to fit."""
    worker_cfg = WorkerConfig(concurrency=20)
    pool_cap = 20
    min_size, max_size, effective = worker_module._calculate_sync_pool_plan(worker_cfg, pool_cap)
    # With pool_cap=20 and SYNC_POOL_OVERHEAD=2, available=18
    # 3 services means max concurrency = 18 // 3 = 6
    assert effective == 6
    assert max_size <= pool_cap
    assert min_size <= max_size


def test_calculate_sync_pool_plan_handles_minimum_concurrency() -> None:
    """Ensure at least concurrency=1 even with tiny pool."""
    worker_cfg = WorkerConfig(concurrency=100)
    pool_cap = 5
    _, _, effective = worker_module._calculate_sync_pool_plan(worker_cfg, pool_cap)
    assert effective >= 1
