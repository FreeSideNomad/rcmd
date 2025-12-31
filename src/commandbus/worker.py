"""Worker for receiving and processing commands from queues."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from commandbus.models import (
    Command,
    CommandMetadata,
    CommandStatus,
    HandlerContext,
    ReplyOutcome,
)
from commandbus.pgmq.client import PgmqClient
from commandbus.repositories.audit import AuditEventType, PostgresAuditLogger
from commandbus.repositories.command import PostgresCommandRepository

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


def _make_queue_name(domain: str, suffix: str = "commands") -> str:
    """Create a queue name from domain."""
    return f"{domain}__{suffix}"


@dataclass
class ReceivedCommand:
    """A command received from the queue, ready for processing.

    Attributes:
        command: The command to process
        context: Handler context with attempt info
        msg_id: PGMQ message ID for acknowledgment
        metadata: Command metadata from storage
    """

    command: Command
    context: HandlerContext
    msg_id: int
    metadata: CommandMetadata


class Worker:
    """Worker for receiving and processing commands.

    The worker reads commands from a domain queue, handles visibility
    timeout for at-least-once delivery, and manages command lifecycle.

    Example:
        pool = AsyncConnectionPool(conninfo)
        await pool.open()
        worker = Worker(pool, domain="payments")

        commands = await worker.receive(batch_size=10)
        for cmd in commands:
            # Process command...
            await worker.complete(cmd)
    """

    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        domain: str,
        visibility_timeout: int = 30,
    ) -> None:
        """Initialize the worker.

        Args:
            pool: psycopg async connection pool
            domain: The domain to process commands for
            visibility_timeout: Default visibility timeout in seconds
        """
        self._pool = pool
        self._domain = domain
        self._visibility_timeout = visibility_timeout
        self._queue_name = _make_queue_name(domain)
        self._pgmq = PgmqClient(pool)
        self._command_repo = PostgresCommandRepository(pool)
        self._audit_logger = PostgresAuditLogger(pool)

    @property
    def domain(self) -> str:
        """Get the domain this worker processes."""
        return self._domain

    @property
    def queue_name(self) -> str:
        """Get the queue name this worker reads from."""
        return self._queue_name

    async def receive(
        self,
        batch_size: int = 1,
        visibility_timeout: int | None = None,
    ) -> list[ReceivedCommand]:
        """Receive commands from the queue.

        Reads messages from the queue and returns them for processing.
        Messages become invisible to other workers for the visibility
        timeout period. If not acknowledged, they reappear for retry.

        Commands in terminal states (COMPLETED, CANCELED) are automatically
        archived and skipped.

        Args:
            batch_size: Maximum number of commands to receive
            visibility_timeout: Override default visibility timeout

        Returns:
            List of received commands (may be empty)
        """
        vt = visibility_timeout or self._visibility_timeout
        received: list[ReceivedCommand] = []

        messages = await self._pgmq.read(
            self._queue_name,
            visibility_timeout=vt,
            batch_size=batch_size,
        )

        for msg in messages:
            try:
                result = await self._process_message(msg.msg_id, msg.message)
                if result is not None:
                    received.append(result)
            except Exception:
                logger.exception(f"Error processing message {msg.msg_id}")
                # Message will reappear after visibility timeout

        return received

    async def _process_message(
        self,
        msg_id: int,
        message: dict[str, Any],
    ) -> ReceivedCommand | None:
        """Process a single message from the queue.

        Args:
            msg_id: PGMQ message ID
            message: Message payload

        Returns:
            ReceivedCommand if ready for processing, None if skipped
        """
        domain = message.get("domain", self._domain)
        command_id_str = message.get("command_id")
        if not command_id_str:
            logger.warning(f"Message {msg_id} missing command_id, archiving")
            await self._pgmq.archive(self._queue_name, msg_id)
            return None

        command_id = UUID(command_id_str)

        # Get command metadata
        metadata = await self._command_repo.get(domain, command_id)
        if metadata is None:
            logger.warning(f"No metadata for command {command_id} in domain {domain}, archiving")
            await self._pgmq.archive(self._queue_name, msg_id)
            return None

        # Skip terminal states
        if metadata.status in (CommandStatus.COMPLETED, CommandStatus.CANCELED):
            logger.debug(
                f"Command {command_id} already in terminal state {metadata.status}, archiving"
            )
            await self._pgmq.archive(self._queue_name, msg_id)
            return None

        # Increment attempts and record audit
        attempts = await self._command_repo.increment_attempts(domain, command_id)

        await self._audit_logger.log(
            domain=domain,
            command_id=command_id,
            event_type=AuditEventType.RECEIVED,
            details={
                "msg_id": msg_id,
                "attempt": attempts,
                "max_attempts": metadata.max_attempts,
            },
        )

        # Update status to IN_PROGRESS
        await self._command_repo.update_status(domain, command_id, CommandStatus.IN_PROGRESS)

        # Build command object
        correlation_id_str = message.get("correlation_id")
        command = Command(
            domain=domain,
            command_type=message.get("command_type", metadata.command_type),
            command_id=command_id,
            data=message.get("data", {}),
            correlation_id=UUID(correlation_id_str) if correlation_id_str else None,
            reply_to=message.get("reply_to"),
            created_at=metadata.created_at,
        )

        # Build context
        context = HandlerContext(
            command=command,
            attempt=attempts,
            max_attempts=metadata.max_attempts,
            msg_id=msg_id,
        )

        # Get updated metadata
        updated_metadata = await self._command_repo.get(domain, command_id)
        if updated_metadata is None:
            updated_metadata = metadata

        logger.info(
            f"Received command {domain}.{command.command_type} "
            f"(command_id={command_id}, attempt={attempts}/{metadata.max_attempts})"
        )

        return ReceivedCommand(
            command=command,
            context=context,
            msg_id=msg_id,
            metadata=updated_metadata,
        )

    async def complete(
        self,
        received: ReceivedCommand,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Complete a command successfully.

        Deletes the message from the queue, updates status to COMPLETED,
        sends a reply if configured, and records an audit event.
        All operations are performed atomically in a single transaction.

        Args:
            received: The received command to complete
            result: Optional result data to include in the reply
        """
        command = received.command
        command_id = command.command_id
        domain = command.domain

        async with self._pool.connection() as conn, conn.transaction():
            # Delete message from queue
            await self._pgmq.delete(self._queue_name, received.msg_id, conn)

            # Update status to COMPLETED
            await self._command_repo.update_status(
                domain, command_id, CommandStatus.COMPLETED, conn
            )

            # Send reply if reply_to is configured
            if command.reply_to:
                reply_message = {
                    "command_id": str(command_id),
                    "correlation_id": str(command.correlation_id)
                    if command.correlation_id
                    else None,
                    "outcome": ReplyOutcome.SUCCESS.value,
                    "result": result,
                }
                await self._pgmq.send(command.reply_to, reply_message, conn=conn)

            # Record audit event
            await self._audit_logger.log(
                domain=domain,
                command_id=command_id,
                event_type=AuditEventType.COMPLETED,
                details={
                    "msg_id": received.msg_id,
                    "reply_to": command.reply_to,
                    "has_result": result is not None,
                },
                conn=conn,
            )

        logger.info(
            f"Completed command {domain}.{command.command_type} "
            f"(command_id={command_id})"
        )
