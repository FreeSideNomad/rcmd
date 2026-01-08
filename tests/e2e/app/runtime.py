"""Runtime manager to toggle between async and sync command bus implementations."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from commandbus import CommandBus, TroubleshootingQueue
from commandbus.process import PostgresProcessRepository
from commandbus.sync import SyncCommandBus, SyncRuntime, SyncTroubleshootingQueue

from .config import RuntimeConfig
from .models import TestCommandRepository
from .process.statement_report import StatementReportProcess


class _RuntimeAdapter:
    """Wraps async objects and optionally dispatches to sync wrappers via a thread."""

    def __init__(
        self,
        mode: str,
        async_obj: Any,
        sync_obj: Any | None = None,
    ) -> None:
        self._mode = mode
        self._async_obj = async_obj
        self._sync_obj = sync_obj

    def __getattr__(self, item: str) -> Any:
        attr = getattr(self._async_obj, item)
        if self._mode != "sync" or self._sync_obj is None:
            return attr

        sync_attr = getattr(self._sync_obj, item, None)
        if not callable(sync_attr):
            return attr

        async def _wrapper(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.to_thread(sync_attr, *args, **kwargs)

        return _wrapper


class RuntimeManager:
    """Coordinates async and sync variants for FastAPI dependencies."""

    def __init__(
        self,
        *,
        pool: Any,
        behavior_repo: TestCommandRepository,
    ) -> None:
        self._pool = pool
        self._behavior_repo = behavior_repo
        self._mode: str = "async"
        self._runtime_config: RuntimeConfig | None = None
        self._async_bus: CommandBus | None = None
        self._async_tsq: TroubleshootingQueue | None = None
        self._process_repo: PostgresProcessRepository | None = None
        self._report_process: StatementReportProcess | None = None
        self._bus_adapter: _RuntimeAdapter | None = None
        self._tsq_adapter: _RuntimeAdapter | None = None
        self._sync_runtime: SyncRuntime | None = None
        self._sync_bus: SyncCommandBus | None = None
        self._sync_tsq: SyncTroubleshootingQueue | None = None

    async def start(self, runtime_config: RuntimeConfig) -> None:
        """Initialize runtime resources based on configuration."""
        await self.shutdown()
        self._runtime_config = runtime_config
        self._mode = runtime_config.mode
        self._async_bus = CommandBus(self._pool)
        self._async_tsq = TroubleshootingQueue(self._pool)
        self._process_repo = PostgresProcessRepository(self._pool)

        if self._mode == "sync":
            self._sync_runtime = SyncRuntime()
            self._sync_bus = SyncCommandBus(bus=self._async_bus, runtime=self._sync_runtime)
            self._sync_tsq = SyncTroubleshootingQueue(
                queue=self._async_tsq, runtime=self._sync_runtime
            )

        self._bus_adapter = _RuntimeAdapter(self._mode, self._async_bus, self._sync_bus)
        self._tsq_adapter = _RuntimeAdapter(self._mode, self._async_tsq, self._sync_tsq)

        self._report_process = StatementReportProcess(
            command_bus=self._bus_adapter,
            process_repo=self._process_repo,
            reply_queue="reporting__process_replies",
            pool=self._pool,
            behavior_repo=self._behavior_repo,
        )

    async def reload_config(self, runtime_config: RuntimeConfig) -> None:
        """Restart runtime resources with a new configuration."""
        await self.start(runtime_config)

    async def shutdown(self) -> None:
        """Clean up runtime-specific resources."""
        if self._sync_runtime is not None:
            self._sync_runtime.shutdown()
        self._bus_adapter = None
        self._tsq_adapter = None
        self._sync_runtime = None
        self._sync_bus = None
        self._sync_tsq = None
        self._async_bus = None
        self._async_tsq = None
        self._process_repo = None
        self._report_process = None

    @property
    def mode(self) -> str:
        """Current runtime mode."""
        return self._mode

    @property
    def runtime_config(self) -> RuntimeConfig | None:
        """Most recent runtime configuration."""
        return self._runtime_config

    @property
    def command_bus(self) -> CommandBus:
        assert self._bus_adapter is not None
        return cast("CommandBus", self._bus_adapter)

    @property
    def troubleshooting_queue(self) -> TroubleshootingQueue:
        assert self._tsq_adapter is not None
        return cast("TroubleshootingQueue", self._tsq_adapter)

    @property
    def process_repository(self) -> PostgresProcessRepository:
        assert self._process_repo is not None
        return self._process_repo

    @property
    def report_process(self) -> StatementReportProcess:
        assert self._report_process is not None
        return self._report_process
