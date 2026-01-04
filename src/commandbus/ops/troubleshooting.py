"""Troubleshooting queue operations for operators."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from commandbus.batch import check_and_invoke_batch_callback
from commandbus.exceptions import CommandNotFoundError, InvalidOperationError
from commandbus.models import CommandStatus, ReplyOutcome, TroubleshootingItem
from commandbus.pgmq.client import PgmqClient
from commandbus.repositories.audit import AuditEventType, PostgresAuditLogger
from commandbus.repositories.batch import PostgresBatchRepository
from commandbus.repositories.command import PostgresCommandRepository

if TYPE_CHECKING:
    from uuid import UUID

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

    async def operator_retry(
        self,
        domain: str,
        command_id: UUID,
        operator: str | None = None,
    ) -> int:
        """Retry a command from the troubleshooting queue.

        Retrieves the original payload from the archive, re-enqueues it to PGMQ,
        resets attempts to 0, sets status to PENDING, and records an audit event.

        Args:
            domain: The domain of the command
            command_id: The command ID to retry
            operator: Optional operator identity for audit trail

        Returns:
            New PGMQ message ID

        Raises:
            CommandNotFoundError: If the command does not exist
            InvalidOperationError: If the command is not in troubleshooting queue
        """
        queue_name = _make_queue_name(domain)
        archive_table = f"pgmq.a_{queue_name}"

        # Create helper instances
        command_repo = PostgresCommandRepository(self._pool)
        batch_repo = PostgresBatchRepository(self._pool)
        pgmq = PgmqClient(self._pool)
        audit_logger = PostgresAuditLogger(self._pool)

        async with self._pool.connection() as conn:
            # Get command metadata
            metadata = await command_repo.get(domain, command_id, conn)
            if metadata is None:
                raise CommandNotFoundError(domain, str(command_id))

            # Verify command is in troubleshooting queue
            if metadata.status != CommandStatus.IN_TROUBLESHOOTING_QUEUE:
                raise InvalidOperationError(
                    f"Command {command_id} is not in troubleshooting queue "
                    f"(status: {metadata.status.value})"
                )

            # Retrieve payload from archive
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT message FROM {archive_table} "
                    "WHERE message->>'command_id' = %s "
                    "ORDER BY msg_id DESC LIMIT 1",
                    (str(command_id),),
                )
                row = await cur.fetchone()

            if row is None:
                raise InvalidOperationError(
                    f"Payload not found in archive for command {command_id}"
                )

            payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]

            # All operations in same transaction
            async with conn.transaction():
                # Send new PGMQ message
                new_msg_id = await pgmq.send(queue_name, payload, conn=conn)

                # Update command metadata: status=PENDING, attempts=0, msg_id=new
                await conn.execute(
                    """
                    UPDATE command_bus_command
                    SET status = %s, attempts = 0, msg_id = %s,
                        last_error_type = NULL, last_error_code = NULL,
                        last_error_msg = NULL, updated_at = NOW()
                    WHERE domain = %s AND command_id = %s
                    """,
                    (CommandStatus.PENDING.value, new_msg_id, domain, command_id),
                )

                # Record audit event
                await audit_logger.log(
                    domain=domain,
                    command_id=command_id,
                    event_type=AuditEventType.OPERATOR_RETRY,
                    details={"operator": operator, "new_msg_id": new_msg_id},
                    conn=conn,
                )

                # Update batch counters on retry (S042)
                if metadata.batch_id is not None:
                    await batch_repo.update_on_tsq_retry(domain, metadata.batch_id, conn=conn)

        logger.info(
            f"Operator retry for {domain}.{command_id}: "
            f"new_msg_id={new_msg_id}, operator={operator}"
        )

        return new_msg_id

    async def operator_cancel(
        self,
        domain: str,
        command_id: UUID,
        reason: str,
        operator: str | None = None,
    ) -> None:
        """Cancel a command in the troubleshooting queue.

        Sets status to CANCELED, sends a CANCELED reply to the reply queue
        (if configured), and records an audit event.

        Args:
            domain: The domain of the command
            command_id: The command ID to cancel
            reason: Reason for cancellation (required)
            operator: Optional operator identity for audit trail

        Raises:
            CommandNotFoundError: If the command does not exist
            InvalidOperationError: If the command is not in troubleshooting queue
        """
        # Create helper instances
        command_repo = PostgresCommandRepository(self._pool)
        batch_repo = PostgresBatchRepository(self._pool)
        pgmq = PgmqClient(self._pool)
        audit_logger = PostgresAuditLogger(self._pool)

        async with self._pool.connection() as conn:
            # Get command metadata
            metadata = await command_repo.get(domain, command_id, conn)
            if metadata is None:
                raise CommandNotFoundError(domain, str(command_id))

            # Verify command is in troubleshooting queue
            if metadata.status != CommandStatus.IN_TROUBLESHOOTING_QUEUE:
                raise InvalidOperationError(
                    f"Command {command_id} is not in troubleshooting queue "
                    f"(status: {metadata.status.value})"
                )

            # All operations in same transaction
            async with conn.transaction():
                # Update command status to CANCELED
                await conn.execute(
                    """
                    UPDATE command_bus_command
                    SET status = %s, updated_at = NOW()
                    WHERE domain = %s AND command_id = %s
                    """,
                    (CommandStatus.CANCELED.value, domain, command_id),
                )

                # Send reply if reply_to is configured
                if metadata.reply_to:
                    reply_message = {
                        "command_id": str(command_id),
                        "correlation_id": str(metadata.correlation_id)
                        if metadata.correlation_id
                        else None,
                        "outcome": ReplyOutcome.CANCELED.value,
                        "reason": reason,
                    }
                    await pgmq.send(metadata.reply_to, reply_message, conn=conn)

                # Record audit event
                await audit_logger.log(
                    domain=domain,
                    command_id=command_id,
                    event_type=AuditEventType.OPERATOR_CANCEL,
                    details={
                        "operator": operator,
                        "reason": reason,
                        "reply_to": metadata.reply_to,
                    },
                    conn=conn,
                )

                # Update batch counters on cancel (S042)
                if metadata.batch_id is not None:
                    await batch_repo.update_on_tsq_cancel(domain, metadata.batch_id, conn=conn)

        logger.info(
            f"Operator cancel for {domain}.{command_id}: reason={reason}, operator={operator}"
        )

        # Check and invoke batch completion callback (S043) - outside transaction
        if metadata.batch_id is not None:
            await check_and_invoke_batch_callback(domain, metadata.batch_id, batch_repo)

    async def operator_complete(
        self,
        domain: str,
        command_id: UUID,
        result_data: dict[str, Any] | None = None,
        operator: str | None = None,
    ) -> None:
        """Manually complete a command in the troubleshooting queue.

        Sets status to COMPLETED, sends a SUCCESS reply to the reply queue
        (if configured) with optional result data, and records an audit event.

        Args:
            domain: The domain of the command
            command_id: The command ID to complete
            result_data: Optional result data to include in the reply
            operator: Optional operator identity for audit trail

        Raises:
            CommandNotFoundError: If the command does not exist
            InvalidOperationError: If the command is not in troubleshooting queue
        """
        # Create helper instances
        command_repo = PostgresCommandRepository(self._pool)
        batch_repo = PostgresBatchRepository(self._pool)
        pgmq = PgmqClient(self._pool)
        audit_logger = PostgresAuditLogger(self._pool)

        async with self._pool.connection() as conn:
            # Get command metadata
            metadata = await command_repo.get(domain, command_id, conn)
            if metadata is None:
                raise CommandNotFoundError(domain, str(command_id))

            # Verify command is in troubleshooting queue
            if metadata.status != CommandStatus.IN_TROUBLESHOOTING_QUEUE:
                raise InvalidOperationError(
                    f"Command {command_id} is not in troubleshooting queue "
                    f"(status: {metadata.status.value})"
                )

            # All operations in same transaction
            async with conn.transaction():
                # Update command status to COMPLETED
                await conn.execute(
                    """
                    UPDATE command_bus_command
                    SET status = %s, updated_at = NOW()
                    WHERE domain = %s AND command_id = %s
                    """,
                    (CommandStatus.COMPLETED.value, domain, command_id),
                )

                # Send reply if reply_to is configured
                if metadata.reply_to:
                    reply_message = {
                        "command_id": str(command_id),
                        "correlation_id": str(metadata.correlation_id)
                        if metadata.correlation_id
                        else None,
                        "outcome": ReplyOutcome.SUCCESS.value,
                        "result": result_data,
                    }
                    await pgmq.send(metadata.reply_to, reply_message, conn=conn)

                # Record audit event
                await audit_logger.log(
                    domain=domain,
                    command_id=command_id,
                    event_type=AuditEventType.OPERATOR_COMPLETE,
                    details={
                        "operator": operator,
                        "has_result_data": result_data is not None,
                        "reply_to": metadata.reply_to,
                    },
                    conn=conn,
                )

                # Update batch counters on complete (S042)
                if metadata.batch_id is not None:
                    await batch_repo.update_on_tsq_complete(domain, metadata.batch_id, conn=conn)

        logger.info(f"Operator complete for {domain}.{command_id}: operator={operator}")

        # Check and invoke batch completion callback (S043) - outside transaction
        if metadata.batch_id is not None:
            await check_and_invoke_batch_callback(domain, metadata.batch_id, batch_repo)
