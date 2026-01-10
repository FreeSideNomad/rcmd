"""E2E Worker with @handler decorator pattern (F007)."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from psycopg_pool import AsyncConnectionPool, ConnectionPool

from commandbus import CommandBus, HandlerRegistry, RetryPolicy, Worker
from commandbus.process import PostgresProcessRepository, ProcessReplyRouter
from commandbus.sync import SyncCommandBus, SyncProcessReplyRouter, SyncWorker
from commandbus.sync.repositories import SyncProcessRepository

from .config import Config, ConfigStore, RetryConfig, WorkerConfig
from .handlers import create_registry
from .handlers.sync_handlers import create_sync_handler_registry
from .models import TestCommandRepository
from .process.statement_report import StatementReportProcess

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

WORKER_DOMAINS: tuple[str, ...] = ("e2e", "reporting")
POOL_HEADROOM = 10
POOL_MIN_SIZE = 2
CONFIG_POOL_MAX = 2
WORKER_CONNECTION_MULTIPLIER = 5
ROUTER_CONNECTION_MULTIPLIER = 3
LISTEN_CONNECTIONS = len(WORKER_DOMAINS) + 1
RESERVED_POOL_GUARD = 5
ENV_POOL_CAP = os.environ.get("E2E_MAX_POOL_SIZE")
# Sync mode: each thread needs a dedicated connection (no cooperative release)
SYNC_CONN_PER_WORKER = 1  # 1 connection per concurrent thread
SYNC_POOL_OVERHEAD = 2  # Extra connections for admin operations


def _calculate_pool_plan(worker_config: WorkerConfig, pool_cap: int) -> tuple[int, int, int]:
    """Determine pool sizing and effective concurrency for async mode."""
    concurrency = max(1, worker_config.concurrency)
    conn_per_tick = (
        len(WORKER_DOMAINS) * WORKER_CONNECTION_MULTIPLIER + ROUTER_CONNECTION_MULTIPLIER
    )
    base_connections = LISTEN_CONNECTIONS
    target_max = base_connections + concurrency * conn_per_tick + POOL_HEADROOM
    capped_max = max(POOL_MIN_SIZE, min(target_max, pool_cap))
    available_slots = max(1, capped_max - base_connections - POOL_HEADROOM)
    supported_concurrency = max(1, min(concurrency, available_slots // conn_per_tick or 1))
    return POOL_MIN_SIZE, capped_max, supported_concurrency


def _calculate_sync_pool_plan(worker_config: WorkerConfig, pool_cap: int) -> tuple[int, int, int]:
    """Determine pool sizing and effective concurrency for sync mode.

    Sync workers require dedicated connections per thread (no cooperative release
    during processing). Each worker domain + router needs `concurrency` connections.
    """
    concurrency = max(1, worker_config.concurrency)
    # Each worker domain + router needs 1 connection per concurrent thread.
    # Total services = number of worker domains + 1 router.
    total_services = len(WORKER_DOMAINS) + 1
    required_connections = total_services * concurrency * SYNC_CONN_PER_WORKER
    target_max = required_connections + SYNC_POOL_OVERHEAD

    if target_max > pool_cap:
        # Cap concurrency to fit within available pool capacity
        available_for_work = max(1, pool_cap - SYNC_POOL_OVERHEAD)
        supported_concurrency = max(1, available_for_work // total_services)
        capped_max = supported_concurrency * total_services + SYNC_POOL_OVERHEAD
    else:
        supported_concurrency = concurrency
        capped_max = target_max

    # Ensure min_size is reasonable (at least supported_concurrency for faster startup)
    pool_min = max(POOL_MIN_SIZE, min(supported_concurrency, capped_max))
    return pool_min, capped_max, supported_concurrency


async def _load_runtime_settings() -> tuple[ConfigStore, int]:
    """Load runtime configuration and determine pool capacity."""
    bootstrap = AsyncConnectionPool(
        conninfo=Config.DATABASE_URL,
        min_size=1,
        max_size=CONFIG_POOL_MAX,
        open=False,
    )
    await bootstrap.open()
    try:
        store = await get_config_store(bootstrap)
        async with bootstrap.connection() as conn, conn.cursor() as cur:
            await cur.execute("SHOW max_connections")
            max_connections = int((await cur.fetchone())[0])
            await cur.execute("SHOW superuser_reserved_connections")
            reserved = int((await cur.fetchone())[0])
        available = max_connections - reserved - RESERVED_POOL_GUARD
        env_cap = int(ENV_POOL_CAP) if ENV_POOL_CAP is not None else None
        server_cap = max(POOL_MIN_SIZE, available)
        pool_cap = min(server_cap, env_cap) if env_cap is not None else server_cap
        return store, pool_cap
    finally:
        await bootstrap.close()


async def create_pool(*, min_size: int, max_size: int) -> AsyncConnectionPool:
    """Create database connection pool with explicit sizing."""
    pool = AsyncConnectionPool(
        conninfo=Config.DATABASE_URL,
        min_size=min_size,
        max_size=max_size,
        open=False,
    )
    await pool.open()
    logger.info("Initialized pool (min_size=%s, max_size=%s)", min_size, max_size)
    return pool


async def get_config_store(pool: AsyncConnectionPool) -> ConfigStore:
    """Get configuration store loaded from database."""
    store = ConfigStore()
    await store.load_from_db(pool)
    return store


def create_worker(
    pool: AsyncConnectionPool,
    domain: str = "e2e",
    retry_config: RetryConfig | None = None,
    visibility_timeout: int = 30,
    registry: HandlerRegistry | None = None,
) -> Worker:
    """Create a worker for a specific domain with configurable settings."""
    if retry_config is None:
        retry_config = RetryConfig()

    if registry is None:
        registry = create_registry(pool)

    retry_policy = RetryPolicy(
        max_attempts=retry_config.max_attempts,
        backoff_schedule=retry_config.backoff_schedule,
    )

    return Worker(
        pool=pool,
        domain=domain,
        registry=registry,
        retry_policy=retry_policy,
        visibility_timeout=visibility_timeout,
    )


async def run_worker(  # noqa: PLR0915
    shutdown_event: asyncio.Event | None = None,
) -> None:
    """Run workers and reply router with configuration from database."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    stop_event = shutdown_event or asyncio.Event()
    loop = asyncio.get_running_loop()
    registered_signals: list[signal.Signals] = []

    def _request_shutdown(sig_name: str) -> None:
        if stop_event.is_set():
            return
        logger.info("Received %s, shutting down workers...", sig_name)
        loop.call_soon_threadsafe(stop_event.set)

    if shutdown_event is None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda s=sig: _request_shutdown(s.name))
                registered_signals.append(sig)
            except NotImplementedError:
                signal.signal(sig, lambda _sig, _frame, s=sig: _request_shutdown(s.name))

    pool: AsyncConnectionPool | None = None
    try:
        config_store, pool_cap = await _load_runtime_settings()
        runtime_mode = config_store.runtime.mode

        # Use different pool planning for sync vs async modes
        if runtime_mode == "sync":
            sync_pool_min, sync_pool_max, effective_concurrency = _calculate_sync_pool_plan(
                config_store.worker, pool_cap
            )
            # Async pool only for process manager (StatementReportProcess).
            # Handlers use native sync with sync pool.
            # Process router has lower throughput - size async pool minimally.
            pool_min, pool_max = POOL_MIN_SIZE, max(POOL_MIN_SIZE, effective_concurrency)
        else:
            pool_min, pool_max, effective_concurrency = _calculate_pool_plan(
                config_store.worker, pool_cap
            )
            sync_pool_min, sync_pool_max = 0, 0  # Not used in async mode

        if effective_concurrency != config_store.worker.concurrency:
            logger.warning(
                "Configured worker concurrency %s exceeds pool capacity, capping to %s",
                config_store.worker.concurrency,
                effective_concurrency,
            )
        worker_config = replace(config_store.worker, concurrency=effective_concurrency)
        logger.info(
            "Pool plan [%s]: cap=%s, pool_min=%s, pool_max=%s, "
            "requested_concurrency=%s, effective_concurrency=%s",
            runtime_mode,
            pool_cap,
            sync_pool_min if runtime_mode == "sync" else pool_min,
            sync_pool_max if runtime_mode == "sync" else pool_max,
            config_store.worker.concurrency,
            worker_config.concurrency,
        )

        pool = await create_pool(min_size=pool_min, max_size=pool_max)
        registry = create_registry(pool)
        bus = CommandBus(pool)
        process_repo = PostgresProcessRepository(pool)
        behavior_repo = TestCommandRepository(pool)

        logger.info(
            "Runtime mode: %s (pool_max=%s, concurrency=%s)",
            runtime_mode,
            sync_pool_max if runtime_mode == "sync" else pool_max,
            worker_config.concurrency,
        )

        if runtime_mode == "sync":
            # Create sync connection pool for native sync components
            # Pool sized to handle all concurrent threads: workers + router
            sync_pool = ConnectionPool(
                conninfo=Config.DATABASE_URL,
                min_size=sync_pool_min,
                max_size=sync_pool_max,
                open=True,
            )
            logger.info(
                "Created sync pool (min_size=%s, max_size=%s) for concurrency=%s",
                sync_pool_min,
                sync_pool_max,
                worker_config.concurrency,
            )

            # Create dedicated pool for router (avoids contention with workers)
            router_pool = ConnectionPool(
                conninfo=Config.DATABASE_URL,
                min_size=5,
                max_size=worker_config.concurrency + 5,
                open=True,
            )
            logger.info(
                "Created router pool (min_size=5, max_size=%s)",
                worker_config.concurrency + 5,
            )

            # Create native sync handlers that use sync pool directly
            # No async wrappers - handlers use sync repositories
            sync_registry = create_sync_handler_registry(sync_pool)

            # Create sync process repository for native router (uses router pool)
            sync_process_repo = SyncProcessRepository(router_pool)

            # Create sync command bus for process manager (uses router pool)
            sync_command_bus = SyncCommandBus(router_pool)

            # Create process manager with sync components for native sync mode
            report_process = StatementReportProcess(
                command_bus=bus,
                process_repo=process_repo,
                reply_queue="reporting__process_replies",
                pool=pool,
                behavior_repo=behavior_repo,
                sync_pool=router_pool,
                sync_command_bus=sync_command_bus,
                sync_process_repo=sync_process_repo,
            )
            managers = {report_process.process_type: report_process}

            # Build retry policy
            retry_policy = RetryPolicy(
                max_attempts=config_store.retry.max_attempts,
                backoff_schedule=config_store.retry.backoff_schedule,
            )

            # Create native sync workers
            sync_e2e = SyncWorker(
                pool=sync_pool,
                domain="e2e",
                registry=sync_registry,
                visibility_timeout=worker_config.visibility_timeout,
                retry_policy=retry_policy,
            )
            sync_reporting = SyncWorker(
                pool=sync_pool,
                domain="reporting",
                registry=sync_registry,
                visibility_timeout=worker_config.visibility_timeout,
                retry_policy=retry_policy,
            )

            # Create native sync process reply router (uses dedicated router pool)
            sync_router = SyncProcessReplyRouter(
                pool=router_pool,
                process_repo=sync_process_repo,
                managers=managers,
                reply_queue="reporting__process_replies",
                domain="reporting",
                visibility_timeout=worker_config.visibility_timeout,
            )

            await _run_sync_services(
                workers=(sync_e2e, sync_reporting),
                router=sync_router,
                worker_config=worker_config,
                stop_event=stop_event,
                sync_pool=sync_pool,
                router_pool=router_pool,
            )
        else:
            # Async mode - create process manager without sync components
            report_process = StatementReportProcess(
                command_bus=bus,
                process_repo=process_repo,
                reply_queue="reporting__process_replies",
                pool=pool,
                behavior_repo=behavior_repo,
            )
            managers = {report_process.process_type: report_process}

            e2e_worker = create_worker(
                pool,
                domain="e2e",
                retry_config=config_store.retry,
                visibility_timeout=worker_config.visibility_timeout,
                registry=registry,
            )
            reporting_worker = create_worker(
                pool,
                domain="reporting",
                retry_config=config_store.retry,
                visibility_timeout=worker_config.visibility_timeout,
                registry=registry,
            )
            router = ProcessReplyRouter(
                pool=pool,
                process_repo=process_repo,
                managers=managers,
                reply_queue="reporting__process_replies",
                domain="reporting",
            )
            await _run_async_services(
                workers=(e2e_worker, reporting_worker),
                router=router,
                worker_config=worker_config,
                stop_event=stop_event,
            )
    finally:
        for sig in registered_signals:
            loop.remove_signal_handler(sig)
        if pool is not None:
            await pool.close()


async def _run_async_services(
    *,
    workers: Sequence[Worker],
    router: ProcessReplyRouter,
    worker_config: WorkerConfig,
    stop_event: asyncio.Event,
) -> None:
    worker_tasks = [
        asyncio.create_task(
            worker.run(
                concurrency=worker_config.concurrency,
                poll_interval=worker_config.poll_interval,
            )
        )
        for worker in workers
    ]
    router_task = asyncio.create_task(
        router.run(
            concurrency=worker_config.concurrency,
            poll_interval=worker_config.poll_interval,
        )
    )
    run_task = asyncio.gather(*worker_tasks, router_task)

    stop_waiter = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {run_task, stop_waiter},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if run_task in done and not stop_event.is_set():
        logger.warning("Worker tasks exited unexpectedly; initiating shutdown")
        stop_event.set()

    await stop_event.wait()
    await router.stop()
    for worker in workers:
        await worker.stop()

    await run_task
    stop_waiter.cancel()
    await asyncio.gather(stop_waiter, return_exceptions=True)


async def _run_sync_services(
    *,
    workers: Sequence[SyncWorker],
    router: SyncProcessReplyRouter,
    worker_config: WorkerConfig,
    stop_event: asyncio.Event,
    sync_pool: ConnectionPool[Any],
    router_pool: ConnectionPool[Any],
) -> None:
    """Run native sync workers and router in background threads."""
    worker_tasks = [
        asyncio.create_task(
            asyncio.to_thread(
                worker.run,
                concurrency=worker_config.concurrency,
                poll_interval=worker_config.poll_interval,
            )
        )
        for worker in workers
    ]

    def _attach_exit_logging(task: asyncio.Task[Any], label: str) -> None:
        def _log_failure(done: asyncio.Task[Any]) -> None:
            if done.cancelled():
                return
            try:
                done.result()
            except Exception:
                logger.exception("%s exited with error", label)

        task.add_done_callback(_log_failure)

    for worker, task in zip(workers, worker_tasks, strict=False):
        domain = getattr(worker, "domain", None)
        worker_label = f"Sync worker for {domain}" if domain else "Sync worker"
        _attach_exit_logging(task, worker_label)

    router_task = asyncio.create_task(
        asyncio.to_thread(
            router.run,
            concurrency=worker_config.concurrency,
            poll_interval=worker_config.poll_interval,
        )
    )
    reply_queue = getattr(router, "_reply_queue", None)
    router_label = (
        f"Sync process router for {reply_queue}" if reply_queue else "Sync process router"
    )
    _attach_exit_logging(router_task, router_label)
    run_task = asyncio.gather(*worker_tasks, router_task)

    stop_waiter = asyncio.create_task(stop_event.wait())
    done, _ = await asyncio.wait(
        {run_task, stop_waiter},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if run_task in done and not stop_event.is_set():
        logger.warning("Sync services exited unexpectedly; initiating shutdown")
        stop_event.set()

    await stop_event.wait()

    # Stop workers and router gracefully
    for worker in workers:
        await asyncio.to_thread(worker.stop)
    await asyncio.to_thread(router.stop)

    await run_task
    stop_waiter.cancel()
    await asyncio.gather(stop_waiter, return_exceptions=True)

    # Close the pools
    sync_pool.close()
    router_pool.close()


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Worker CLI interrupted by user")
