"""Troubleshooting queue operations for operators."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from commandbus.models import CommandStatus, TroubleshootingItem

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


def _make_queue_name(domain: str, suffix: str = "commands") -> str:
    """Create a queue name from domain."""
    return f"{domain}__{suffix}"


class TroubleshootingQueue:
    """Operations for managing commands in the troubleshooting queue.

    The troubleshooting queue contains commands that failed permanently
    or exhausted retries. Operators can list, retry, cancel, or complete
    these commands.

    Example:
        pool = AsyncConnectionPool(conninfo)
        await pool.open()

        tsq = TroubleshootingQueue(pool)
        items = await tsq.list_troubleshooting(domain="payments")
        for item in items:
            print(f"{item.command_type}: {item.last_error_msg}")
    """

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        """Initialize the troubleshooting queue.

        Args:
            pool: psycopg async connection pool
        """
        self._pool = pool

    async def list_troubleshooting(
        self,
        domain: str,
        command_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TroubleshootingItem]:
        """List commands in the troubleshooting queue for a domain.

        Retrieves commands with status IN_TROUBLESHOOTING_QUEUE, including
        the original payload from the PGMQ archive table.

        Args:
            domain: The domain to list troubleshooting items for
            command_type: Optional filter by command type
            limit: Maximum number of items to return (default 50)
            offset: Number of items to skip for pagination (default 0)

        Returns:
            List of TroubleshootingItem objects
        """
        queue_name = _make_queue_name(domain)
        archive_table = f"pgmq.a_{queue_name}"

        # Build the query with optional command_type filter
        query = f"""
            SELECT
                c.domain,
                c.command_id,
                c.command_type,
                c.attempts,
                c.max_attempts,
                c.last_error_type,
                c.last_error_code,
                c.last_error_msg,
                c.correlation_id,
                c.reply_queue,
                a.message,
                c.created_at,
                c.updated_at
            FROM command_bus_command c
            LEFT JOIN {archive_table} a ON a.message->>'command_id' = c.command_id::text
            WHERE c.domain = %s
              AND c.status = %s
        """

        params: list[Any] = [domain, CommandStatus.IN_TROUBLESHOOTING_QUEUE.value]

        if command_type is not None:
            query += " AND c.command_type = %s"
            params.append(command_type)

        query += " ORDER BY c.updated_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        items: list[TroubleshootingItem] = []

        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

            for row in rows:
                # Parse the archived message payload
                if row[10] is None:
                    payload = None
                else:
                    payload = json.loads(row[10]) if isinstance(row[10], str) else row[10]

                items.append(
                    TroubleshootingItem(
                        domain=row[0],
                        command_id=row[1],
                        command_type=row[2],
                        attempts=row[3],
                        max_attempts=row[4],
                        last_error_type=row[5],
                        last_error_code=row[6],
                        last_error_msg=row[7],
                        correlation_id=row[8],
                        reply_to=row[9] if row[9] else None,
                        payload=payload,
                        created_at=row[11],
                        updated_at=row[12],
                    )
                )

        logger.debug(
            f"Listed {len(items)} troubleshooting items for {domain}"
            f" (limit={limit}, offset={offset})"
        )

        return items

    async def count_troubleshooting(
        self,
        domain: str,
        command_type: str | None = None,
    ) -> int:
        """Count commands in the troubleshooting queue for a domain.

        Args:
            domain: The domain to count troubleshooting items for
            command_type: Optional filter by command type

        Returns:
            Number of commands in troubleshooting queue
        """
        query = """
            SELECT COUNT(*)
            FROM command_bus_command
            WHERE domain = %s
              AND status = %s
        """

        params: list[Any] = [domain, CommandStatus.IN_TROUBLESHOOTING_QUEUE.value]

        if command_type is not None:
            query += " AND command_type = %s"
            params.append(command_type)

        async with self._pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            return int(row[0]) if row else 0
