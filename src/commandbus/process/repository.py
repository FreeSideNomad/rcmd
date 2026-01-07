"""Process repository for database persistence."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from psycopg.types.json import Jsonb

from commandbus.models import ReplyOutcome
from commandbus.process.models import (
    ProcessAuditEntry,
    ProcessMetadata,
    ProcessStatus,
)

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg import AsyncConnection
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class ProcessRepository(Protocol):
    """Protocol for process persistence."""

    async def save(
        self,
        process: ProcessMetadata[Any, Any],
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Save a new process."""
        ...

    async def update(
        self,
        process: ProcessMetadata[Any, Any],
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update existing process."""
        ...

    async def get_by_id(
        self,
        domain: str,
        process_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> ProcessMetadata[Any, Any] | None:
        """Get process by ID."""
        ...

    async def find_by_status(
        self,
        domain: str,
        statuses: list[ProcessStatus],
        conn: AsyncConnection[Any] | None = None,
    ) -> list[ProcessMetadata[Any, Any]]:
        """Find processes by status."""
        ...

    async def log_step(
        self,
        domain: str,
        process_id: UUID,
        entry: ProcessAuditEntry,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Log a step execution to audit trail."""
        ...

    async def update_step_reply(
        self,
        domain: str,
        process_id: UUID,
        command_id: UUID,
        entry: ProcessAuditEntry,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update step with reply information."""
        ...

    async def get_audit_trail(
        self,
        domain: str,
        process_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> list[ProcessAuditEntry]:
        """Get full audit trail for a process."""
        ...

    async def get_completed_steps(
        self,
        domain: str,
        process_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> list[str]:
        """Get list of completed step names (for compensation)."""
        ...


class PostgresProcessRepository:
    """PostgreSQL implementation of ProcessRepository."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        """Initialize the repository.

        Args:
            pool: psycopg async connection pool
        """
        self._pool = pool

    async def save(
        self,
        process: ProcessMetadata[Any, Any],
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Save a new process."""
        state_data = process.state
        if hasattr(state_data, "to_dict"):
            state_data = state_data.to_dict()

        if conn:
            await self._save(conn, process, state_data)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._save(acquired_conn, process, state_data)

    async def _save(
        self,
        conn: AsyncConnection[Any],
        process: ProcessMetadata[Any, Any],
        state_data: dict[str, Any],
    ) -> None:
        await conn.execute(
            """
            INSERT INTO commandbus.process (
                domain, process_id, process_type, status, current_step,
                state, error_code, error_message,
                created_at, updated_at, completed_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s
            )
            """,
            (
                process.domain,
                process.process_id,
                process.process_type,
                process.status.value,
                process.current_step,
                Jsonb(state_data),
                process.error_code,
                process.error_message,
                process.created_at,
                process.updated_at,
                process.completed_at,
            ),
        )
        logger.debug(f"Saved process {process.domain}.{process.process_id}")

    async def update(
        self,
        process: ProcessMetadata[Any, Any],
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update existing process."""
        # Note: We do NOT update updated_at here manually because AC3 says
        # "updated_at is automatically set to NOW()".
        # But commonly we might want to update the object's timestamp too.
        # The design doc shows manual update in python object before DB call.
        # I'll update Python object's timestamp before saving.
        # However, relying on DB NOW() is safer for consistency.
        # Let's stick to explicit update from Python object matching design doc.

        state_data = process.state
        if hasattr(state_data, "to_dict"):
            state_data = state_data.to_dict()

        if conn:
            await self._update(conn, process, state_data)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._update(acquired_conn, process, state_data)

    async def _update(
        self,
        conn: AsyncConnection[Any],
        process: ProcessMetadata[Any, Any],
        state_data: dict[str, Any],
    ) -> None:
        await conn.execute(
            """
            UPDATE commandbus.process SET
                status = %s,
                current_step = %s,
                state = %s,
                error_code = %s,
                error_message = %s,
                updated_at = NOW(),
                completed_at = %s
            WHERE domain = %s AND process_id = %s
            """,
            (
                process.status.value,
                process.current_step,
                Jsonb(state_data),
                process.error_code,
                process.error_message,
                # updated_at is handled by NOW() in SQL as per AC3
                process.completed_at,
                process.domain,
                process.process_id,
            ),
        )

    async def get_by_id(
        self,
        domain: str,
        process_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> ProcessMetadata[Any, Any] | None:
        """Get process by ID."""
        if conn:
            return await self._get_by_id(conn, domain, process_id)

        async with self._pool.connection() as acquired_conn:
            return await self._get_by_id(acquired_conn, domain, process_id)

    async def _get_by_id(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        process_id: UUID,
    ) -> ProcessMetadata[Any, Any] | None:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT domain, process_id, process_type, status, current_step,
                       state, error_code, error_message,
                       created_at, updated_at, completed_at
                FROM commandbus.process
                WHERE domain = %s AND process_id = %s
                """,
                (domain, process_id),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            return self._row_to_metadata(row)

    def _row_to_metadata(self, row: Any) -> ProcessMetadata[Any, Any]:
        """Convert database row to ProcessMetadata."""
        return ProcessMetadata(
            domain=row[0],
            process_id=row[1],
            process_type=row[2],
            status=ProcessStatus(row[3]),
            current_step=row[4],
            state=row[5],  # psycopg returns dict for JSONB
            error_code=row[6],
            error_message=row[7],
            created_at=row[8],
            updated_at=row[9],
            completed_at=row[10],
        )

    async def find_by_status(
        self,
        domain: str,
        statuses: list[ProcessStatus],
        conn: AsyncConnection[Any] | None = None,
    ) -> list[ProcessMetadata[Any, Any]]:
        """Find processes by status."""
        status_values = [s.value for s in statuses]

        if conn:
            return await self._find_by_status(conn, domain, status_values)

        async with self._pool.connection() as acquired_conn:
            return await self._find_by_status(acquired_conn, domain, status_values)

    async def _find_by_status(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        status_values: list[str],
    ) -> list[ProcessMetadata[Any, Any]]:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT domain, process_id, process_type, status, current_step,
                       state, error_code, error_message,
                       created_at, updated_at, completed_at
                FROM commandbus.process
                WHERE domain = %s AND status = ANY(%s)
                """,
                (domain, status_values),
            )
            rows = await cur.fetchall()
            return [self._row_to_metadata(row) for row in rows]

    async def log_step(
        self,
        domain: str,
        process_id: UUID,
        entry: ProcessAuditEntry,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Log a step execution to audit trail."""
        if conn:
            await self._log_step(conn, domain, process_id, entry)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._log_step(acquired_conn, domain, process_id, entry)

    async def _log_step(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        process_id: UUID,
        entry: ProcessAuditEntry,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO commandbus.process_audit (
                domain, process_id, step_name, command_id, command_type,
                command_data, sent_at, reply_outcome, reply_data, received_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                domain,
                process_id,
                entry.step_name,
                entry.command_id,
                entry.command_type,
                Jsonb(entry.command_data) if entry.command_data is not None else None,
                entry.sent_at,
                entry.reply_outcome.value if entry.reply_outcome else None,
                Jsonb(entry.reply_data) if entry.reply_data is not None else None,
                entry.received_at,
            ),
        )

    async def update_step_reply(
        self,
        domain: str,
        process_id: UUID,
        command_id: UUID,
        entry: ProcessAuditEntry,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update step with reply information."""
        if conn:
            await self._update_step_reply(conn, domain, process_id, command_id, entry)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._update_step_reply(acquired_conn, domain, process_id, command_id, entry)

    async def _update_step_reply(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        process_id: UUID,
        command_id: UUID,
        entry: ProcessAuditEntry,
    ) -> None:
        await conn.execute(
            """
            UPDATE commandbus.process_audit SET
                reply_outcome = %s,
                reply_data = %s,
                received_at = %s
            WHERE domain = %s AND process_id = %s AND command_id = %s
            """,
            (
                entry.reply_outcome.value if entry.reply_outcome else None,
                Jsonb(entry.reply_data) if entry.reply_data is not None else None,
                entry.received_at,
                domain,
                process_id,
                command_id,
            ),
        )

    async def get_audit_trail(
        self,
        domain: str,
        process_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> list[ProcessAuditEntry]:
        """Get full audit trail for a process."""
        if conn:
            return await self._get_audit_trail(conn, domain, process_id)
        else:
            async with self._pool.connection() as acquired_conn:
                return await self._get_audit_trail(acquired_conn, domain, process_id)

    async def _get_audit_trail(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        process_id: UUID,
    ) -> list[ProcessAuditEntry]:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT step_name, command_id, command_type, command_data,
                       sent_at, reply_outcome, reply_data, received_at
                FROM commandbus.process_audit
                WHERE domain = %s AND process_id = %s
                ORDER BY sent_at ASC
                """,
                (domain, process_id),
            )
            rows = await cur.fetchall()
            return [
                ProcessAuditEntry(
                    step_name=row[0],
                    command_id=row[1],
                    command_type=row[2],
                    command_data=row[3],
                    sent_at=row[4],
                    reply_outcome=ReplyOutcome(row[5]) if row[5] else None,
                    reply_data=row[6],
                    received_at=row[7],
                )
                for row in rows
            ]

    async def get_completed_steps(
        self,
        domain: str,
        process_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> list[str]:
        """Get list of completed step names (for compensation)."""
        if conn:
            return await self._get_completed_steps(conn, domain, process_id)
        else:
            async with self._pool.connection() as acquired_conn:
                return await self._get_completed_steps(acquired_conn, domain, process_id)

    async def _get_completed_steps(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        process_id: UUID,
    ) -> list[str]:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT step_name
                FROM commandbus.process_audit
                WHERE domain = %s AND process_id = %s AND reply_outcome = 'SUCCESS'
                ORDER BY sent_at ASC
                """,
                (domain, process_id),
            )
            rows = await cur.fetchall()
            return [row[0] for row in rows]
