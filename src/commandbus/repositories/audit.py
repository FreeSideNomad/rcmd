"""Audit logging for command bus events."""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg import AsyncConnection
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    """Types of audit events."""

    SENT = "SENT"
    RECEIVED = "RECEIVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    MOVED_TO_TSQ = "MOVED_TO_TSQ"
    OPERATOR_RETRY = "OPERATOR_RETRY"
    OPERATOR_CANCEL = "OPERATOR_CANCEL"
    OPERATOR_COMPLETE = "OPERATOR_COMPLETE"


class AuditLogger(Protocol):
    """Protocol for audit logging."""

    async def log(
        self,
        domain: str,
        command_id: UUID,
        event_type: AuditEventType,
        details: dict[str, Any] | None = None,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Log an audit event."""
        ...


class PostgresAuditLogger:
    """PostgreSQL implementation of audit logging."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        """Initialize the audit logger.

        Args:
            pool: psycopg async connection pool
        """
        self._pool = pool

    async def log(
        self,
        domain: str,
        command_id: UUID,
        event_type: AuditEventType,
        details: dict[str, Any] | None = None,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Log an audit event to the database.

        Args:
            domain: The domain of the command
            command_id: The command ID
            event_type: Type of audit event
            details: Optional additional details
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._log(conn, domain, command_id, event_type, details)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._log(acquired_conn, domain, command_id, event_type, details)

    async def _log(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        event_type: AuditEventType,
        details: dict[str, Any] | None,
    ) -> None:
        """Log using an existing connection."""
        details_json = json.dumps(details) if details else None
        await conn.execute(
            """
            INSERT INTO command_bus_audit (domain, command_id, event_type, details_json)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (domain, command_id, event_type.value, details_json),
        )
        logger.debug(f"Audit: {event_type.value} for {domain}.{command_id}")

    async def get_events(
        self,
        command_id: UUID,
        domain: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get audit events for a command.

        Args:
            command_id: The command ID
            domain: Optional domain filter

        Returns:
            List of audit events
        """
        async with self._pool.connection() as conn:
            async with conn.cursor() as cur:
                if domain:
                    await cur.execute(
                        """
                        SELECT audit_id, domain, command_id, event_type, ts, details_json
                        FROM command_bus_audit
                        WHERE command_id = %s AND domain = %s
                        ORDER BY ts ASC
                        """,
                        (command_id, domain),
                    )
                else:
                    await cur.execute(
                        """
                        SELECT audit_id, domain, command_id, event_type, ts, details_json
                        FROM command_bus_audit
                        WHERE command_id = %s
                        ORDER BY ts ASC
                        """,
                        (command_id,),
                    )
                rows = await cur.fetchall()

            return [
                {
                    "audit_id": row[0],
                    "domain": row[1],
                    "command_id": row[2],
                    "event_type": row[3],
                    "ts": row[4],
                    "details": json.loads(row[5]) if row[5] else None,
                }
                for row in rows
            ]
