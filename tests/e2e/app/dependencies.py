"""FastAPI dependency injection for E2E demo application."""

from typing import Annotated

from fastapi import Depends, Request
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.ops.troubleshooting import TroubleshootingQueue
from commandbus.process import ProcessRepository

from .process.statement_report import StatementReportProcess
from .runtime import RuntimeManager


async def get_pool(request: Request) -> AsyncConnectionPool:
    """Get database pool from app state."""
    return request.app.state.pool


async def get_runtime_manager(request: Request) -> RuntimeManager:
    """Get runtime manager from app state."""
    manager = getattr(request.app.state, "runtime_manager", None)
    if manager is None:  # pragma: no cover - defensive guard
        raise RuntimeError("Runtime manager is not initialized")
    return manager


async def get_command_bus(
    manager: Annotated[RuntimeManager, Depends(get_runtime_manager)],
) -> CommandBus:
    """Get CommandBus instance that respects runtime mode."""
    return manager.command_bus


async def get_tsq(
    manager: Annotated[RuntimeManager, Depends(get_runtime_manager)],
) -> TroubleshootingQueue:
    """Get TroubleshootingQueue instance."""
    return manager.troubleshooting_queue


async def get_process_repo(
    manager: Annotated[RuntimeManager, Depends(get_runtime_manager)],
) -> ProcessRepository:
    """Get ProcessRepository from runtime manager."""
    return manager.process_repository


async def get_report_process(
    manager: Annotated[RuntimeManager, Depends(get_runtime_manager)],
) -> StatementReportProcess:
    """Get StatementReportProcess from runtime manager."""
    return manager.report_process


# Type aliases for cleaner route signatures
Pool = Annotated[AsyncConnectionPool, Depends(get_pool)]
Bus = Annotated[CommandBus, Depends(get_command_bus)]
TSQ = Annotated[TroubleshootingQueue, Depends(get_tsq)]
ProcessRepo = Annotated[ProcessRepository, Depends(get_process_repo)]
ReportProcess = Annotated[StatementReportProcess, Depends(get_report_process)]
