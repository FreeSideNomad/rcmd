"""Native synchronous command repository.

This module provides a synchronous command repository using psycopg3's
thread-safe ConnectionPool for native sync operations without
async wrapper overhead.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from commandbus._core.command_sql import CommandParams, CommandParsers, CommandSQL
from commandbus.models import CommandMetadata, CommandStatus

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg import Connection
    from psycopg_pool import ConnectionPool

logger = logging.getLogger(__name__)


class SyncCommandRepository:
    """Synchronous command repository using native sync connections.

    This repository provides sync methods for command metadata persistence,
    using psycopg3's thread-safe ConnectionPool. Each method accepts an
    optional connection parameter for transaction support.

    Example:
        pool = ConnectionPool(conninfo=DATABASE_URL)
        repo = SyncCommandRepository(pool)

        # Save command metadata
        repo.save(metadata, queue_name)

        # Get command by ID
        metadata = repo.get(domain, command_id)

        # Use stored procedures
        result = repo.sp_receive_command(domain, command_id)
    """

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        """Initialize the sync command repository.

        Args:
            pool: psycopg sync connection pool
        """
        self._pool = pool

    def save(
        self,
        metadata: CommandMetadata,
        queue_name: str,
        conn: Connection[Any] | None = None,
    ) -> None:
        """Save command metadata to the database.

        Args:
            metadata: Command metadata to save
            queue_name: The queue name for this command
            conn: Optional connection (for transaction support)
        """
        sql = CommandSQL.SAVE
        params = CommandParams.save(metadata, queue_name)

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

        logger.debug("Saved command metadata: %s.%s", metadata.domain, metadata.command_id)

    def save_batch(
        self,
        metadata_list: list[CommandMetadata],
        queue_name: str,
        conn: Connection[Any],
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

        sql = CommandSQL.SAVE
        params_list = [CommandParams.save(m, queue_name) for m in metadata_list]

        with conn.cursor() as cur:
            cur.executemany(sql, params_list)

        logger.debug("Saved %d command metadata records", len(metadata_list))

    def exists_batch(
        self,
        domain: str,
        command_ids: list[UUID],
        conn: Connection[Any],
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

        with conn.cursor() as cur:
            cur.execute(CommandSQL.EXISTS_BATCH, (domain, command_ids))
            rows = cur.fetchall()
            return {row[0] for row in rows}

    def get(
        self,
        domain: str,
        command_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> CommandMetadata | None:
        """Get command metadata by domain and command_id.

        Args:
            domain: The domain
            command_id: The command ID
            conn: Optional connection (for transaction support)

        Returns:
            CommandMetadata if found, None otherwise
        """
        sql = CommandSQL.GET
        params = (domain, command_id)

        if conn is not None:
            return self._get_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._get_with_conn(c, sql, params)

    def _get_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, UUID],
    ) -> CommandMetadata | None:
        """Get metadata using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()

        if row is None:
            return None

        return CommandParsers.from_row(row)

    def update_status(
        self,
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        conn: Connection[Any] | None = None,
    ) -> None:
        """Update command status.

        Args:
            domain: The domain
            command_id: The command ID
            status: New status
            conn: Optional connection (for transaction support)
        """
        sql = CommandSQL.UPDATE_STATUS
        params = CommandParams.update_status(status, domain, command_id)

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

        logger.debug("Updated status for %s.%s to %s", domain, command_id, status.value)

    def update_msg_id(
        self,
        domain: str,
        command_id: UUID,
        msg_id: int,
        conn: Connection[Any] | None = None,
    ) -> None:
        """Update the message ID for a command.

        Args:
            domain: The domain
            command_id: The command ID
            msg_id: The PGMQ message ID
            conn: Optional connection (for transaction support)
        """
        sql = CommandSQL.UPDATE_MSG_ID
        params = CommandParams.update_msg_id(msg_id, domain, command_id)

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

    def increment_attempts(
        self,
        domain: str,
        command_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> int:
        """Increment attempts counter and return new value.

        Args:
            domain: The domain
            command_id: The command ID
            conn: Optional connection (for transaction support)

        Returns:
            New attempts value after increment
        """
        sql = CommandSQL.INCREMENT_ATTEMPTS
        params = (domain, command_id)

        if conn is not None:
            return self._increment_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._increment_with_conn(c, sql, params)

    def _increment_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, UUID],
    ) -> int:
        """Increment attempts using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def receive_command(
        self,
        domain: str,
        command_id: UUID,
        new_status: CommandStatus = CommandStatus.IN_PROGRESS,
        conn: Connection[Any] | None = None,
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
        sql = CommandSQL.RECEIVE_COMMAND
        params = CommandParams.receive_command(new_status, domain, command_id)

        if conn is not None:
            return self._receive_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._receive_with_conn(c, sql, params)

    def _receive_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, str, UUID],
    ) -> tuple[CommandMetadata, int] | None:
        """Receive command using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()

        if row is None:
            return None

        metadata = CommandParsers.from_row(row)
        return metadata, metadata.attempts

    def update_error(
        self,
        domain: str,
        command_id: UUID,
        error_type: str,
        error_code: str,
        error_msg: str,
        conn: Connection[Any] | None = None,
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
        sql = CommandSQL.UPDATE_ERROR
        params = CommandParams.update_error(error_type, error_code, error_msg, domain, command_id)

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

        logger.debug("Updated error for %s.%s: [%s] %s", domain, command_id, error_code, error_msg)

    def finish_command(
        self,
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        error_type: str | None = None,
        error_code: str | None = None,
        error_msg: str | None = None,
        conn: Connection[Any] | None = None,
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
        sql = CommandSQL.FINISH_COMMAND
        params = CommandParams.finish_command(
            status, error_type, error_code, error_msg, domain, command_id
        )

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

        logger.debug("Finished %s.%s with status %s", domain, command_id, status.value)

    def exists(
        self,
        domain: str,
        command_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> bool:
        """Check if a command exists.

        Args:
            domain: The domain
            command_id: The command ID
            conn: Optional connection (for transaction support)

        Returns:
            True if command exists, False otherwise
        """
        sql = CommandSQL.EXISTS
        params = (domain, command_id)

        if conn is not None:
            return self._exists_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._exists_with_conn(c, sql, params)

    def _exists_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, UUID],
    ) -> bool:
        """Check existence using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return bool(row[0]) if row else False

    def list_by_batch(
        self,
        domain: str,
        batch_id: UUID,
        *,
        status: CommandStatus | None = None,
        limit: int = 100,
        offset: int = 0,
        conn: Connection[Any] | None = None,
    ) -> list[CommandMetadata]:
        """List commands belonging to a specific batch.

        Args:
            domain: The domain
            batch_id: The batch ID to filter by
            status: Optional filter by command status
            limit: Maximum number of results (default 100)
            offset: Number of results to skip (default 0)
            conn: Optional connection (for transaction support)

        Returns:
            List of CommandMetadata for commands in the batch
        """
        if status is not None:
            sql = CommandSQL.LIST_BY_BATCH_WITH_STATUS
            params: tuple[Any, ...] = (domain, batch_id, status.value, limit, offset)
        else:
            sql = CommandSQL.LIST_BY_BATCH
            params = (domain, batch_id, limit, offset)

        if conn is not None:
            return self._list_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._list_with_conn(c, sql, params)

    def _list_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[Any, ...],
    ) -> list[CommandMetadata]:
        """List commands using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return CommandParsers.from_rows(rows)

    # =========================================================================
    # Stored Procedure Methods
    # =========================================================================

    def sp_receive_command(
        self,
        domain: str,
        command_id: UUID,
        msg_id: int | None = None,
        max_attempts: int | None = None,
        conn: Connection[Any] | None = None,
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
        sql = CommandSQL.SP_RECEIVE_COMMAND
        params = CommandParams.sp_receive_command(
            domain, command_id, "IN_PROGRESS", msg_id, max_attempts
        )

        if conn is not None:
            return self._sp_receive_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._sp_receive_with_conn(c, sql, params)

    def _sp_receive_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, UUID, str, int | None, int | None],
    ) -> tuple[CommandMetadata, int] | None:
        """Call sp_receive_command stored procedure."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()

        if row is None:
            return None

        metadata = CommandParsers.from_row(row)
        return metadata, metadata.attempts

    def sp_finish_command(
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
        conn: Connection[Any] | None = None,
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
        params = CommandParams.sp_finish_command(
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

        if conn is not None:
            return self._sp_finish_with_conn(conn, params)
        else:
            with self._pool.connection() as c:
                return self._sp_finish_with_conn(c, params)

    def _sp_finish_with_conn(
        self,
        conn: Connection[Any],
        params: tuple[
            str, UUID, str, str, str | None, str | None, str | None, str | None, UUID | None
        ],
    ) -> bool:
        """Call sp_finish_command stored procedure."""
        with conn.cursor() as cur:
            cur.execute(CommandSQL.SP_FINISH_COMMAND, params)
            row = cur.fetchone()
            return bool(row[0]) if row else False

    def sp_fail_command(
        self,
        domain: str,
        command_id: UUID,
        error_type: str,
        error_code: str,
        error_msg: str,
        attempt: int,
        max_attempts: int,
        msg_id: int,
        conn: Connection[Any] | None = None,
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
        params = CommandParams.sp_fail_command(
            domain, command_id, error_type, error_code, error_msg, attempt, max_attempts, msg_id
        )

        if conn is not None:
            return self._sp_fail_with_conn(conn, params)
        else:
            with self._pool.connection() as c:
                return self._sp_fail_with_conn(c, params)

    def _sp_fail_with_conn(
        self,
        conn: Connection[Any],
        params: tuple[str, UUID, str, str, str, int, int, int],
    ) -> bool:
        """Call sp_fail_command stored procedure."""
        with conn.cursor() as cur:
            cur.execute(CommandSQL.SP_FAIL_COMMAND, params)
            row = cur.fetchone()
            return bool(row[0]) if row else False
