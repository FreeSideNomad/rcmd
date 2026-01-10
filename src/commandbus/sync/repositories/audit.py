"""Native synchronous audit logger.

This module provides a synchronous audit logger using psycopg3's
thread-safe ConnectionPool for native sync operations without
async wrapper overhead.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from commandbus.models import AuditEvent
from commandbus.repositories.audit import AuditEventType  # noqa: TC001 (runtime use)

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg import Connection
    from psycopg_pool import ConnectionPool


logger = logging.getLogger(__name__)


class SyncAuditLogger:
    """Synchronous audit logger using native sync connections.

    This logger provides sync methods for audit event persistence,
    using psycopg3's thread-safe ConnectionPool. Each method accepts an
    optional connection parameter for transaction support.

    Example:
        pool = ConnectionPool(conninfo=DATABASE_URL)
        logger = SyncAuditLogger(pool)

        # Log an event
        logger.log(domain, command_id, AuditEventType.SENT)

        # Log with transaction
        with pool.connection() as conn:
            with conn.transaction():
                logger.log(domain, command_id, AuditEventType.COMPLETED, conn=conn)
    """

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        """Initialize the sync audit logger.

        Args:
            pool: psycopg sync connection pool
        """
        self._pool = pool

    def log(
        self,
        domain: str,
        command_id: UUID,
        event_type: AuditEventType,
        details: dict[str, Any] | None = None,
        conn: Connection[Any] | None = None,
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
            self._log(conn, domain, command_id, event_type, details)
        else:
            with self._pool.connection() as acquired_conn:
                self._log(acquired_conn, domain, command_id, event_type, details)

    def _log(
        self,
        conn: Connection[Any],
        domain: str,
        command_id: UUID,
        event_type: AuditEventType,
        details: dict[str, Any] | None,
    ) -> None:
        """Log using an existing connection."""
        details_json = json.dumps(details) if details else None
        conn.execute(
            """
            INSERT INTO commandbus.audit (domain, command_id, event_type, details_json)
            VALUES (%s, %s, %s, %s::jsonb)
            """,
            (domain, command_id, event_type.value, details_json),
        )
        logger.debug("Audit: %s for %s.%s", event_type.value, domain, command_id)

    def log_batch(
        self,
        events: list[tuple[str, UUID, AuditEventType, dict[str, Any] | None]],
        conn: Connection[Any],
    ) -> None:
        """Log multiple audit events in a single operation.

        Args:
            events: List of tuples (domain, command_id, event_type, details)
            conn: Database connection (required for batch operation)
        """
        if not events:
            return

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO commandbus.audit (domain, command_id, event_type, details_json)
                VALUES (%s, %s, %s, %s::jsonb)
                """,
                [
                    (
                        domain,
                        command_id,
                        event_type.value,
                        json.dumps(details) if details else None,
                    )
                    for domain, command_id, event_type, details in events
                ],
            )
        logger.debug("Logged %d audit events", len(events))

    def get_events(
        self,
        command_id: UUID,
        domain: str | None = None,
        conn: Connection[Any] | None = None,
    ) -> list[AuditEvent]:
        """Get audit events for a command.

        Args:
            command_id: The command ID
            domain: Optional domain filter
            conn: Optional connection (for transaction support)

        Returns:
            List of audit events ordered by timestamp ascending
        """
        if conn is not None:
            return self._get_events(conn, command_id, domain)
        else:
            with self._pool.connection() as acquired_conn:
                return self._get_events(acquired_conn, command_id, domain)

    def _get_events(
        self,
        conn: Connection[Any],
        command_id: UUID,
        domain: str | None,
    ) -> list[AuditEvent]:
        """Get events using an existing connection."""
        with conn.cursor() as cur:
            if domain:
                cur.execute(
                    """
                    SELECT audit_id, domain, command_id, event_type, ts, details_json
                    FROM commandbus.audit
                    WHERE command_id = %s AND domain = %s
                    ORDER BY ts ASC
                    """,
                    (command_id, domain),
                )
            else:
                cur.execute(
                    """
                    SELECT audit_id, domain, command_id, event_type, ts, details_json
                    FROM commandbus.audit
                    WHERE command_id = %s
                    ORDER BY ts ASC
                    """,
                    (command_id,),
                )
            rows = cur.fetchall()

        return [
            AuditEvent(
                audit_id=row[0],
                domain=row[1],
                command_id=row[2],
                event_type=row[3],
                timestamp=row[4],
                details=row[5] if row[5] else None,
            )
            for row in rows
        ]
