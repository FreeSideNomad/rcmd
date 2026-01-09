"""E2E Worker with @handler decorator pattern (F007)."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import TYPE_CHECKING, Any

from psycopg_pool import AsyncConnectionPool

from commandbus import CommandBus, HandlerRegistry, RetryPolicy, Worker
from commandbus.process import PostgresProcessRepository, ProcessReplyRouter
from commandbus.sync import SyncProcessReplyRouter, SyncRuntime, SyncWorker
from commandbus.sync.config import get_thread_pool_size as get_sync_thread_pool_size

from .config import Config, ConfigStore, RetryConfig, WorkerConfig
from .handlers import create_registry
from .models import TestCommandRepository
from .process.statement_report import StatementReportProcess

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


async def create_pool() -> AsyncConnectionPool:
    """Create database connection pool."""
    pool = AsyncConnectionPool(
        conninfo=Config.DATABASE_URL,
        min_size=2,
        max_size=10,
    )
    await pool.open()
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

    pool = await create_pool()
    registry = create_registry(pool)
    bus = CommandBus(pool)
    process_repo = PostgresProcessRepository(pool)
    behavior_repo = TestCommandRepository(pool)

    report_process = StatementReportProcess(
        command_bus=bus,
        process_repo=process_repo,
        reply_queue="reporting__process_replies",
        pool=pool,
        behavior_repo=behavior_repo,
    )
    managers = {report_process.process_type: report_process}

    sync_runtime: SyncRuntime | None = None
    try:
        config_store = await get_config_store(pool)
        runtime_mode = config_store.runtime.mode
        thread_pool_size = config_store.runtime.thread_pool_size
        effective_threads = get_sync_thread_pool_size(thread_pool_size)
        logger.info(
            "Runtime mode: %s (thread_pool_size=%s)",
            runtime_mode,
            effective_threads if runtime_mode == "sync" else "async-event-loop",
        )

        if runtime_mode == "sync":
            sync_runtime = SyncRuntime()
            base_e2e_worker = create_worker(
                pool,
                domain="e2e",
                retry_config=config_store.retry,
                visibility_timeout=config_store.worker.visibility_timeout,
                registry=registry,
            )
            base_reporting_worker = create_worker(
                pool,
                domain="reporting",
                retry_config=config_store.retry,
                visibility_timeout=config_store.worker.visibility_timeout,
                registry=registry,
            )
            sync_e2e = SyncWorker(
                worker=base_e2e_worker,
                runtime=sync_runtime,
                thread_pool_size=thread_pool_size,
            )
            sync_reporting = SyncWorker(
                worker=base_reporting_worker,
                runtime=sync_runtime,
                thread_pool_size=thread_pool_size,
            )
            base_router = ProcessReplyRouter(
                pool=pool,
                process_repo=process_repo,
                managers=managers,
                reply_queue="reporting__process_replies",
                domain="reporting",
            )
            sync_router = SyncProcessReplyRouter(
                router=base_router,
                runtime=sync_runtime,
                thread_pool_size=thread_pool_size,
            )
            await _run_sync_services(
                workers=(sync_e2e, sync_reporting),
                router=sync_router,
                worker_config=config_store.worker,
                stop_event=stop_event,
            )
        else:
            e2e_worker = create_worker(
                pool,
                domain="e2e",
                retry_config=config_store.retry,
                visibility_timeout=config_store.worker.visibility_timeout,
                registry=registry,
            )
            reporting_worker = create_worker(
                pool,
                domain="reporting",
                retry_config=config_store.retry,
                visibility_timeout=config_store.worker.visibility_timeout,
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
                worker_config=config_store.worker,
                stop_event=stop_event,
            )
    finally:
        for sig in registered_signals:
            loop.remove_signal_handler(sig)
        try:
            if sync_runtime is not None:
                sync_runtime.shutdown()
        finally:
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
) -> None:
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
    reply_queue = getattr(router, "reply_queue", None)
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
    for worker in workers:
        await asyncio.to_thread(worker.stop)
    await asyncio.to_thread(router.stop)

    await run_task
    stop_waiter.cancel()
    await asyncio.gather(stop_waiter, return_exceptions=True)
    for worker in workers:
        await asyncio.to_thread(worker.shutdown)
    await asyncio.to_thread(router.shutdown)


if __name__ == "__main__":
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("Worker CLI interrupted by user")
