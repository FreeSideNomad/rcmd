"""Repository for command metadata storage."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from commandbus.models import CommandMetadata, CommandStatus

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from psycopg import AsyncConnection
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class CommandRepository(Protocol):
    """Protocol for command metadata storage."""

    async def save(
        self,
        metadata: CommandMetadata,
        queue_name: str,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Save command metadata."""
        ...

    async def get(
        self,
        domain: str,
        command_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> CommandMetadata | None:
        """Get command metadata by domain and command_id."""
        ...

    async def update_status(
        self,
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update command status."""
        ...

    async def exists(
        self,
        domain: str,
        command_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> bool:
        """Check if a command exists."""
        ...

    async def query(
        self,
        status: CommandStatus | None = None,
        domain: str | None = None,
        command_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CommandMetadata]:
        """Query commands with filters."""
        ...


class PostgresCommandRepository:
    """PostgreSQL implementation of CommandRepository."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        """Initialize the repository.

        Args:
            pool: psycopg async connection pool
        """
        self._pool = pool

    async def save(
        self,
        metadata: CommandMetadata,
        queue_name: str,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Save command metadata to the database.

        Args:
            metadata: Command metadata to save
            queue_name: The queue name for this command
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._save(conn, metadata, queue_name)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._save(acquired_conn, metadata, queue_name)

    async def _save(
        self,
        conn: AsyncConnection[Any],
        metadata: CommandMetadata,
        queue_name: str,
    ) -> None:
        """Save metadata using an existing connection."""
        await conn.execute(
            """
            INSERT INTO commandbus.command (
                domain, queue_name, msg_id, command_id, command_type,
                status, attempts, max_attempts, correlation_id, reply_queue,
                created_at, updated_at, batch_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                metadata.domain,
                queue_name,
                metadata.msg_id,
                metadata.command_id,
                metadata.command_type,
                metadata.status.value,
                metadata.attempts,
                metadata.max_attempts,
                metadata.correlation_id,
                metadata.reply_to or "",
                metadata.created_at,
                metadata.updated_at,
                metadata.batch_id,
            ),
        )
        logger.debug(f"Saved command metadata: {metadata.domain}.{metadata.command_id}")

    async def save_batch(
        self,
        metadata_list: list[CommandMetadata],
        queue_name: str,
        conn: AsyncConnection[Any],
    ) -> None:
        """Save multiple command metadata records in a single operation.

        This is more efficient than calling save() multiple times.

        Args:
            metadata_list: List of command metadata to save
            queue_name: The queue name for these commands
            conn: Database connection (required for batch operation)
        """
        if not metadata_list:
            return

        async with conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO commandbus.command (
                    domain, queue_name, msg_id, command_id, command_type,
                    status, attempts, max_attempts, correlation_id, reply_queue,
                    created_at, updated_at, batch_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        m.domain,
                        queue_name,
                        m.msg_id,
                        m.command_id,
                        m.command_type,
                        m.status.value,
                        m.attempts,
                        m.max_attempts,
                        m.correlation_id,
                        m.reply_to or "",
                        m.created_at,
                        m.updated_at,
                        m.batch_id,
                    )
                    for m in metadata_list
                ],
            )
        logger.debug(f"Saved {len(metadata_list)} command metadata records")

    async def exists_batch(
        self,
        domain: str,
        command_ids: list[UUID],
        conn: AsyncConnection[Any],
    ) -> set[UUID]:
        """Check which command IDs already exist.

        Args:
            domain: The domain
            command_ids: List of command IDs to check
            conn: Database connection

        Returns:
            Set of command IDs that already exist
        """
        if not command_ids:
            return set()

        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT command_id FROM commandbus.command
                WHERE domain = %s AND command_id = ANY(%s)
                """,
                (domain, command_ids),
            )
            rows = await cur.fetchall()
            return {row[0] for row in rows}

    async def get(
        self,
        domain: str,
        command_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> CommandMetadata | None:
        """Get command metadata by domain and command_id.

        Args:
            domain: The domain
            command_id: The command ID
            conn: Optional connection (for transaction support)

        Returns:
            CommandMetadata if found, None otherwise
        """
        if conn is not None:
            return await self._get(conn, domain, command_id)

        async with self._pool.connection() as acquired_conn:
            return await self._get(acquired_conn, domain, command_id)

    async def _get(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
    ) -> CommandMetadata | None:
        """Get metadata using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT domain, command_id, command_type, status, attempts,
                       max_attempts, msg_id, correlation_id, reply_queue,
                       last_error_type, last_error_code, last_error_msg,
                       created_at, updated_at, batch_id
                FROM commandbus.command
                WHERE domain = %s AND command_id = %s
                """,
                (domain, command_id),
            )
            row = await cur.fetchone()

        if row is None:
            return None

        return CommandMetadata(
            domain=row[0],
            command_id=row[1],
            command_type=row[2],
            status=CommandStatus(row[3]),
            attempts=row[4],
            max_attempts=row[5],
            msg_id=row[6],
            correlation_id=row[7],
            reply_to=row[8] if row[8] else None,
            last_error_type=row[9],
            last_error_code=row[10],
            last_error_msg=row[11],
            created_at=row[12],
            updated_at=row[13],
            batch_id=row[14],
        )

    async def update_status(
        self,
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update command status.

        Args:
            domain: The domain
            command_id: The command ID
            status: New status
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._update_status(conn, domain, command_id, status)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._update_status(acquired_conn, domain, command_id, status)

    async def _update_status(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        status: CommandStatus,
    ) -> None:
        """Update status using an existing connection."""
        await conn.execute(
            """
            UPDATE commandbus.command
            SET status = %s, updated_at = NOW()
            WHERE domain = %s AND command_id = %s
            """,
            (status.value, domain, command_id),
        )
        logger.debug(f"Updated status for {domain}.{command_id} to {status.value}")

    async def update_msg_id(
        self,
        domain: str,
        command_id: UUID,
        msg_id: int,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update the message ID for a command.

        Args:
            domain: The domain
            command_id: The command ID
            msg_id: The PGMQ message ID
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._update_msg_id(conn, domain, command_id, msg_id)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._update_msg_id(acquired_conn, domain, command_id, msg_id)

    async def _update_msg_id(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        msg_id: int,
    ) -> None:
        """Update msg_id using an existing connection."""
        await conn.execute(
            """
            UPDATE commandbus.command
            SET msg_id = %s, updated_at = NOW()
            WHERE domain = %s AND command_id = %s
            """,
            (msg_id, domain, command_id),
        )

    async def increment_attempts(
        self,
        domain: str,
        command_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> int:
        """Increment attempts counter and return new value.

        Args:
            domain: The domain
            command_id: The command ID
            conn: Optional connection (for transaction support)

        Returns:
            New attempts value after increment
        """
        if conn is not None:
            return await self._increment_attempts(conn, domain, command_id)

        async with self._pool.connection() as acquired_conn:
            return await self._increment_attempts(acquired_conn, domain, command_id)

    async def _increment_attempts(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
    ) -> int:
        """Increment attempts using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE commandbus.command
                SET attempts = attempts + 1, updated_at = NOW()
                WHERE domain = %s AND command_id = %s
                RETURNING attempts
                """,
                (domain, command_id),
            )
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def receive_command(
        self,
        domain: str,
        command_id: UUID,
        new_status: CommandStatus = CommandStatus.IN_PROGRESS,
        conn: AsyncConnection[Any] | None = None,
    ) -> tuple[CommandMetadata, int] | None:
        """Atomically get metadata, increment attempts, and update status.

        This combines get(), increment_attempts(), and update_status() into a
        single database round-trip for better performance.

        Args:
            domain: The domain
            command_id: The command ID
            new_status: Status to set (default: IN_PROGRESS)
            conn: Optional connection (for transaction support)

        Returns:
            Tuple of (CommandMetadata, new_attempts) if found, None otherwise
        """
        if conn is not None:
            return await self._receive_command(conn, domain, command_id, new_status)

        async with self._pool.connection() as acquired_conn:
            return await self._receive_command(acquired_conn, domain, command_id, new_status)

    async def _receive_command(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        new_status: CommandStatus,
    ) -> tuple[CommandMetadata, int] | None:
        """Receive command using an existing connection.

        Uses a single UPDATE ... RETURNING to atomically:
        1. Check command is not in terminal state (COMPLETED, CANCELED)
        2. Increment attempts
        3. Update status to new_status
        4. Return all metadata fields

        Returns None if command not found OR if in terminal state.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE commandbus.command
                SET attempts = attempts + 1,
                    status = %s,
                    updated_at = NOW()
                WHERE domain = %s AND command_id = %s
                  AND status NOT IN ('COMPLETED', 'CANCELED')
                RETURNING domain, command_id, command_type, status, attempts,
                          max_attempts, msg_id, correlation_id, reply_queue,
                          last_error_type, last_error_code, last_error_msg,
                          created_at, updated_at, batch_id
                """,
                (new_status.value, domain, command_id),
            )
            row = await cur.fetchone()

        if row is None:
            return None

        metadata = CommandMetadata(
            domain=row[0],
            command_id=row[1],
            command_type=row[2],
            status=CommandStatus(row[3]),
            attempts=row[4],
            max_attempts=row[5],
            msg_id=row[6],
            correlation_id=row[7],
            reply_to=row[8] if row[8] else None,
            last_error_type=row[9],
            last_error_code=row[10],
            last_error_msg=row[11],
            created_at=row[12],
            updated_at=row[13],
            batch_id=row[14],
        )
        # attempts is already incremented in the UPDATE
        return metadata, metadata.attempts

    async def update_error(
        self,
        domain: str,
        command_id: UUID,
        error_type: str,
        error_code: str,
        error_msg: str,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update the last error information for a command.

        Args:
            domain: The domain
            command_id: The command ID
            error_type: Type of error (e.g., 'TRANSIENT', 'PERMANENT')
            error_code: Error code
            error_msg: Error message
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._update_error(conn, domain, command_id, error_type, error_code, error_msg)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._update_error(
                    acquired_conn, domain, command_id, error_type, error_code, error_msg
                )

    async def _update_error(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        error_type: str,
        error_code: str,
        error_msg: str,
    ) -> None:
        """Update error info using an existing connection."""
        await conn.execute(
            """
            UPDATE commandbus.command
            SET last_error_type = %s, last_error_code = %s, last_error_msg = %s,
                updated_at = NOW()
            WHERE domain = %s AND command_id = %s
            """,
            (error_type, error_code, error_msg, domain, command_id),
        )
        logger.debug(f"Updated error for {domain}.{command_id}: [{error_code}] {error_msg}")

    async def finish_command(
        self,
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        error_type: str | None = None,
        error_code: str | None = None,
        error_msg: str | None = None,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Atomically update status and error info in a single query.

        This combines update_status() and update_error() into one DB round-trip.
        Use this for command completion (success or failure).

        Args:
            domain: The domain
            command_id: The command ID
            status: New status
            error_type: Type of error (optional, for failures)
            error_code: Error code (optional, for failures)
            error_msg: Error message (optional, for failures)
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._finish_command(
                conn, domain, command_id, status, error_type, error_code, error_msg
            )
        else:
            async with self._pool.connection() as acquired_conn:
                await self._finish_command(
                    acquired_conn, domain, command_id, status, error_type, error_code, error_msg
                )

    async def _finish_command(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        error_type: str | None,
        error_code: str | None,
        error_msg: str | None,
    ) -> None:
        """Finish command using an existing connection."""
        await conn.execute(
            """
            UPDATE commandbus.command
            SET status = %s,
                last_error_type = COALESCE(%s, last_error_type),
                last_error_code = COALESCE(%s, last_error_code),
                last_error_msg = COALESCE(%s, last_error_msg),
                updated_at = NOW()
            WHERE domain = %s AND command_id = %s
            """,
            (status.value, error_type, error_code, error_msg, domain, command_id),
        )
        logger.debug(f"Finished {domain}.{command_id} with status {status.value}")

    async def exists(
        self,
        domain: str,
        command_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> bool:
        """Check if a command exists.

        Args:
            domain: The domain
            command_id: The command ID
            conn: Optional connection (for transaction support)

        Returns:
            True if command exists, False otherwise
        """
        if conn is not None:
            return await self._exists(conn, domain, command_id)

        async with self._pool.connection() as acquired_conn:
            return await self._exists(acquired_conn, domain, command_id)

    async def _exists(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
    ) -> bool:
        """Check existence using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM commandbus.command
                    WHERE domain = %s AND command_id = %s
                )
                """,
                (domain, command_id),
            )
            row = await cur.fetchone()
            return bool(row[0]) if row else False

    async def list_by_batch(
        self,
        domain: str,
        batch_id: UUID,
        *,
        status: CommandStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CommandMetadata]:
        """List commands belonging to a specific batch.

        Args:
            domain: The domain
            batch_id: The batch ID to filter by
            status: Optional filter by command status
            limit: Maximum number of results (default 100)
            offset: Number of results to skip (default 0)

        Returns:
            List of CommandMetadata for commands in the batch
        """
        async with self._pool.connection() as conn:
            return await self._list_by_batch(conn, domain, batch_id, status, limit, offset)

    async def _list_by_batch(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        batch_id: UUID,
        status: CommandStatus | None,
        limit: int,
        offset: int,
    ) -> list[CommandMetadata]:
        """List commands by batch using an existing connection."""
        conditions = ["domain = %s", "batch_id = %s"]
        params: list[Any] = [domain, batch_id]

        if status is not None:
            conditions.append("status = %s")
            params.append(status.value)

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT domain, command_id, command_type, status, attempts,
                       max_attempts, msg_id, correlation_id, reply_queue,
                       last_error_type, last_error_code, last_error_msg,
                       created_at, updated_at, batch_id
                FROM commandbus.command
                WHERE {where_clause}
                ORDER BY created_at ASC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = await cur.fetchall()

        return [
            CommandMetadata(
                domain=row[0],
                command_id=row[1],
                command_type=row[2],
                status=CommandStatus(row[3]),
                attempts=row[4],
                max_attempts=row[5],
                msg_id=row[6],
                correlation_id=row[7],
                reply_to=row[8] if row[8] else None,
                last_error_type=row[9],
                last_error_code=row[10],
                last_error_msg=row[11],
                created_at=row[12],
                updated_at=row[13],
                batch_id=row[14],
            )
            for row in rows
        ]

    async def query(
        self,
        status: CommandStatus | None = None,
        domain: str | None = None,
        command_type: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CommandMetadata]:
        """Query commands with filters.

        Args:
            status: Filter by status
            domain: Filter by domain
            command_type: Filter by command type
            created_after: Filter by created_at >= this datetime
            created_before: Filter by created_at <= this datetime
            limit: Maximum number of results (default 100)
            offset: Number of results to skip (default 0)

        Returns:
            List of CommandMetadata matching the filters, ordered by created_at DESC
        """
        async with self._pool.connection() as conn:
            return await self._query(
                conn, status, domain, command_type, created_after, created_before, limit, offset
            )

    async def sp_receive_command(
        self,
        domain: str,
        command_id: UUID,
        msg_id: int | None = None,
        max_attempts: int | None = None,
        conn: AsyncConnection[Any] | None = None,
    ) -> tuple[CommandMetadata, int] | None:
        """Receive command using stored procedure.

        This combines receive_command + audit logging into a single DB call.
        Uses sp_receive_command stored procedure for maximum performance.

        Args:
            domain: The domain
            command_id: The command ID
            msg_id: The PGMQ message ID (for audit)
            max_attempts: Override max_attempts (for audit)
            conn: Optional connection (for transaction support)

        Returns:
            Tuple of (CommandMetadata, new_attempts) if found, None otherwise
        """
        if conn is not None:
            return await self._sp_receive_command(conn, domain, command_id, msg_id, max_attempts)

        async with self._pool.connection() as acquired_conn:
            return await self._sp_receive_command(
                acquired_conn, domain, command_id, msg_id, max_attempts
            )

    async def _sp_receive_command(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        msg_id: int | None,
        max_attempts: int | None,
    ) -> tuple[CommandMetadata, int] | None:
        """Call sp_receive_command stored procedure."""
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM commandbus.sp_receive_command(%s, %s, %s, %s, %s)",
                (domain, command_id, "IN_PROGRESS", msg_id, max_attempts),
            )
            row = await cur.fetchone()

        if row is None:
            return None

        metadata = CommandMetadata(
            domain=row[0],
            command_id=row[1],
            command_type=row[2],
            status=CommandStatus(row[3]),
            attempts=row[4],
            max_attempts=row[5],
            msg_id=row[6],
            correlation_id=row[7],
            reply_to=row[8] if row[8] else None,
            last_error_type=row[9],
            last_error_code=row[10],
            last_error_msg=row[11],
            created_at=row[12],
            updated_at=row[13],
            batch_id=row[14],  # S042: Include batch_id for status tracking
        )
        return metadata, metadata.attempts

    async def sp_finish_command(
        self,
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        event_type: str,
        error_type: str | None = None,
        error_code: str | None = None,
        error_msg: str | None = None,
        details: dict[str, Any] | None = None,
        batch_id: UUID | None = None,
        conn: AsyncConnection[Any] | None = None,
    ) -> bool:
        """Finish command using stored procedure.

        This combines finish_command + audit logging + batch counter update
        into a single DB call. Uses sp_finish_command stored procedure.

        Args:
            domain: The domain
            command_id: The command ID
            status: New status
            event_type: Audit event type (e.g., 'COMPLETED', 'MOVED_TO_TSQ')
            error_type: Type of error (optional, for failures)
            error_code: Error code (optional, for failures)
            error_msg: Error message (optional, for failures)
            details: Additional audit details (optional)
            batch_id: Batch ID for batch counter updates (optional)
            conn: Optional connection (for transaction support)

        Returns:
            True if batch is now complete (for callback triggering), False otherwise
        """
        details_json = json.dumps(details) if details else None

        if conn is not None:
            return await self._sp_finish_command(
                conn,
                domain,
                command_id,
                status,
                event_type,
                error_type,
                error_code,
                error_msg,
                details_json,
                batch_id,
            )

        async with self._pool.connection() as acquired_conn:
            return await self._sp_finish_command(
                acquired_conn,
                domain,
                command_id,
                status,
                event_type,
                error_type,
                error_code,
                error_msg,
                details_json,
                batch_id,
            )

    async def _sp_finish_command(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        event_type: str,
        error_type: str | None,
        error_code: str | None,
        error_msg: str | None,
        details_json: str | None,
        batch_id: UUID | None,
    ) -> bool:
        """Call sp_finish_command stored procedure."""
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT commandbus.sp_finish_command(%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
                (
                    domain,
                    command_id,
                    status.value,
                    event_type,
                    error_type,
                    error_code,
                    error_msg,
                    details_json,
                    batch_id,
                ),
            )
            row = await cur.fetchone()
            return bool(row[0]) if row else False

    async def sp_fail_command(
        self,
        domain: str,
        command_id: UUID,
        error_type: str,
        error_code: str,
        error_msg: str,
        attempt: int,
        max_attempts: int,
        msg_id: int,
        conn: AsyncConnection[Any] | None = None,
    ) -> bool:
        """Record command failure using stored procedure.

        This combines update_error + audit logging into a single DB call.
        Uses sp_fail_command stored procedure for maximum performance.

        Args:
            domain: The domain
            command_id: The command ID
            error_type: Type of error (e.g., 'TRANSIENT', 'PERMANENT')
            error_code: Error code
            error_msg: Error message
            attempt: Current attempt number
            max_attempts: Maximum attempts allowed
            msg_id: PGMQ message ID
            conn: Optional connection (for transaction support)

        Returns:
            True if command was found and updated, False otherwise
        """
        if conn is not None:
            return await self._sp_fail_command(
                conn,
                domain,
                command_id,
                error_type,
                error_code,
                error_msg,
                attempt,
                max_attempts,
                msg_id,
            )

        async with self._pool.connection() as acquired_conn:
            return await self._sp_fail_command(
                acquired_conn,
                domain,
                command_id,
                error_type,
                error_code,
                error_msg,
                attempt,
                max_attempts,
                msg_id,
            )

    async def _sp_fail_command(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        command_id: UUID,
        error_type: str,
        error_code: str,
        error_msg: str,
        attempt: int,
        max_attempts: int,
        msg_id: int,
    ) -> bool:
        """Call sp_fail_command stored procedure."""
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT commandbus.sp_fail_command(%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    domain,
                    command_id,
                    error_type,
                    error_code,
                    error_msg,
                    attempt,
                    max_attempts,
                    msg_id,
                ),
            )
            row = await cur.fetchone()
            return bool(row[0]) if row else False

    async def _query(
        self,
        conn: AsyncConnection[Any],
        status: CommandStatus | None,
        domain: str | None,
        command_type: str | None,
        created_after: datetime | None,
        created_before: datetime | None,
        limit: int,
        offset: int,
    ) -> list[CommandMetadata]:
        """Query using an existing connection."""
        conditions: list[str] = []
        params: list[Any] = []

        if status is not None:
            conditions.append("status = %s")
            params.append(status.value)

        if domain is not None:
            conditions.append("domain = %s")
            params.append(domain)

        if command_type is not None:
            conditions.append("command_type = %s")
            params.append(command_type)

        if created_after is not None:
            conditions.append("created_at >= %s")
            params.append(created_after)

        if created_before is not None:
            conditions.append("created_at <= %s")
            params.append(created_before)

        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        params.extend([limit, offset])

        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT domain, command_id, command_type, status, attempts,
                       max_attempts, msg_id, correlation_id, reply_queue,
                       last_error_type, last_error_code, last_error_msg,
                       created_at, updated_at, batch_id
                FROM commandbus.command
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = await cur.fetchall()

        return [
            CommandMetadata(
                domain=row[0],
                command_id=row[1],
                command_type=row[2],
                status=CommandStatus(row[3]),
                attempts=row[4],
                max_attempts=row[5],
                msg_id=row[6],
                correlation_id=row[7],
                reply_to=row[8] if row[8] else None,
                last_error_type=row[9],
                last_error_code=row[10],
                last_error_msg=row[11],
                created_at=row[12],
                updated_at=row[13],
                batch_id=row[14],
            )
            for row in rows
        ]
