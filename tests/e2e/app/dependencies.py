"""FastAPI dependency injection for E2E demo application."""

from typing import Annotated

from fastapi import Depends, Request
from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.ops.troubleshooting import TroubleshootingQueue
from commandbus.process import ProcessRepository

from .process.statement_report import StatementReportProcess


async def get_pool(request: Request) -> AsyncConnectionPool:
    """Get database pool from app state."""
    return request.app.state.pool


async def get_command_bus(request: Request) -> CommandBus:
    """Get CommandBus instance from app state."""
    return request.app.state.bus


async def get_tsq(
    pool: Annotated[AsyncConnectionPool, Depends(get_pool)],
) -> TroubleshootingQueue:
    """Get TroubleshootingQueue instance."""
    return TroubleshootingQueue(pool)


async def get_process_repo(request: Request) -> ProcessRepository:
    """Get ProcessRepository from app state."""
    return request.app.state.process_repo


async def get_report_process(request: Request) -> StatementReportProcess:
    """Get StatementReportProcess from app state."""
    return request.app.state.report_process


# Type aliases for cleaner route signatures
Pool = Annotated[AsyncConnectionPool, Depends(get_pool)]
Bus = Annotated[CommandBus, Depends(get_command_bus)]
TSQ = Annotated[TroubleshootingQueue, Depends(get_tsq)]
ProcessRepo = Annotated[ProcessRepository, Depends(get_process_repo)]
ReportProcess = Annotated[StatementReportProcess, Depends(get_report_process)]
