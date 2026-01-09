"""SQL constants, parameter builders, and row parsers for command operations.

This module extracts shared SQL logic for both async and sync implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from commandbus.models import CommandMetadata, CommandStatus

if TYPE_CHECKING:
    from uuid import UUID


class CommandSQL:
    """SQL constants for command operations."""

    # Column order for SELECT queries - used by all GET/RECEIVE operations
    SELECT_COLUMNS = """
        domain, command_id, command_type, status, attempts,
        max_attempts, msg_id, correlation_id, reply_queue,
        last_error_type, last_error_code, last_error_msg,
        created_at, updated_at, batch_id
    """

    SAVE = """
        INSERT INTO commandbus.command (
            domain, queue_name, msg_id, command_id, command_type,
            status, attempts, max_attempts, correlation_id, reply_queue,
            created_at, updated_at, batch_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    GET = f"""
        SELECT {SELECT_COLUMNS}
        FROM commandbus.command
        WHERE domain = %s AND command_id = %s
    """

    UPDATE_STATUS = """
        UPDATE commandbus.command
        SET status = %s, updated_at = NOW()
        WHERE domain = %s AND command_id = %s
    """

    UPDATE_MSG_ID = """
        UPDATE commandbus.command
        SET msg_id = %s, updated_at = NOW()
        WHERE domain = %s AND command_id = %s
    """

    INCREMENT_ATTEMPTS = """
        UPDATE commandbus.command
        SET attempts = attempts + 1, updated_at = NOW()
        WHERE domain = %s AND command_id = %s
        RETURNING attempts
    """

    RECEIVE_COMMAND = f"""
        UPDATE commandbus.command
        SET attempts = attempts + 1,
            status = %s,
            updated_at = NOW()
        WHERE domain = %s AND command_id = %s
          AND status NOT IN ('COMPLETED', 'CANCELED')
        RETURNING {SELECT_COLUMNS}
    """

    UPDATE_ERROR = """
        UPDATE commandbus.command
        SET last_error_type = %s, last_error_code = %s, last_error_msg = %s,
            updated_at = NOW()
        WHERE domain = %s AND command_id = %s
    """

    FINISH_COMMAND = """
        UPDATE commandbus.command
        SET status = %s,
            last_error_type = COALESCE(%s, last_error_type),
            last_error_code = COALESCE(%s, last_error_code),
            last_error_msg = COALESCE(%s, last_error_msg),
            updated_at = NOW()
        WHERE domain = %s AND command_id = %s
    """

    EXISTS = """
        SELECT EXISTS(
            SELECT 1 FROM commandbus.command
            WHERE domain = %s AND command_id = %s
        )
    """

    EXISTS_BATCH = """
        SELECT command_id FROM commandbus.command
        WHERE domain = %s AND command_id = ANY(%s)
    """

    LIST_BY_BATCH = f"""
        SELECT {SELECT_COLUMNS}
        FROM commandbus.command
        WHERE domain = %s AND batch_id = %s
        ORDER BY created_at ASC
        LIMIT %s OFFSET %s
    """

    LIST_BY_BATCH_WITH_STATUS = f"""
        SELECT {SELECT_COLUMNS}
        FROM commandbus.command
        WHERE domain = %s AND batch_id = %s AND status = %s
        ORDER BY created_at ASC
        LIMIT %s OFFSET %s
    """

    # Stored procedure calls
    SP_RECEIVE_COMMAND = "SELECT * FROM commandbus.sp_receive_command(%s, %s, %s, %s, %s)"

    SP_FINISH_COMMAND = (
        "SELECT commandbus.sp_finish_command(%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)"
    )

    SP_FAIL_COMMAND = "SELECT commandbus.sp_fail_command(%s, %s, %s, %s, %s, %s, %s, %s)"


class CommandParams:
    """Static methods for building SQL parameter tuples."""

    @staticmethod
    def save(metadata: CommandMetadata, queue_name: str) -> tuple[Any, ...]:
        """Build parameters for SAVE query.

        Args:
            metadata: Command metadata to save
            queue_name: The queue name for this command

        Returns:
            Tuple of 13 parameters for SAVE SQL
        """
        return (
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
        )

    @staticmethod
    def update_status(
        status: CommandStatus, domain: str, command_id: UUID
    ) -> tuple[str, str, UUID]:
        """Build parameters for UPDATE_STATUS query."""
        return (status.value, domain, command_id)

    @staticmethod
    def update_msg_id(msg_id: int, domain: str, command_id: UUID) -> tuple[int, str, UUID]:
        """Build parameters for UPDATE_MSG_ID query."""
        return (msg_id, domain, command_id)

    @staticmethod
    def receive_command(
        new_status: CommandStatus, domain: str, command_id: UUID
    ) -> tuple[str, str, UUID]:
        """Build parameters for RECEIVE_COMMAND query."""
        return (new_status.value, domain, command_id)

    @staticmethod
    def update_error(
        error_type: str,
        error_code: str,
        error_msg: str,
        domain: str,
        command_id: UUID,
    ) -> tuple[str, str, str, str, UUID]:
        """Build parameters for UPDATE_ERROR query."""
        return (error_type, error_code, error_msg, domain, command_id)

    @staticmethod
    def finish_command(
        status: CommandStatus,
        error_type: str | None,
        error_code: str | None,
        error_msg: str | None,
        domain: str,
        command_id: UUID,
    ) -> tuple[str, str | None, str | None, str | None, str, UUID]:
        """Build parameters for FINISH_COMMAND query."""
        return (status.value, error_type, error_code, error_msg, domain, command_id)

    @staticmethod
    def sp_receive_command(
        domain: str,
        command_id: UUID,
        new_status: str = "IN_PROGRESS",
        msg_id: int | None = None,
        max_attempts: int | None = None,
    ) -> tuple[str, UUID, str, int | None, int | None]:
        """Build parameters for SP_RECEIVE_COMMAND call."""
        return (domain, command_id, new_status, msg_id, max_attempts)

    @staticmethod
    def sp_finish_command(
        domain: str,
        command_id: UUID,
        status: CommandStatus,
        event_type: str,
        error_type: str | None,
        error_code: str | None,
        error_msg: str | None,
        details_json: str | None,
        batch_id: UUID | None,
    ) -> tuple[str, UUID, str, str, str | None, str | None, str | None, str | None, UUID | None]:
        """Build parameters for SP_FINISH_COMMAND call."""
        return (
            domain,
            command_id,
            status.value,
            event_type,
            error_type,
            error_code,
            error_msg,
            details_json,
            batch_id,
        )

    @staticmethod
    def sp_fail_command(
        domain: str,
        command_id: UUID,
        error_type: str,
        error_code: str,
        error_msg: str,
        attempt: int,
        max_attempts: int,
        msg_id: int,
    ) -> tuple[str, UUID, str, str, str, int, int, int]:
        """Build parameters for SP_FAIL_COMMAND call."""
        return (
            domain,
            command_id,
            error_type,
            error_code,
            error_msg,
            attempt,
            max_attempts,
            msg_id,
        )


class CommandParsers:
    """Static methods for parsing database rows to CommandMetadata."""

    @staticmethod
    def from_row(row: tuple[Any, ...]) -> CommandMetadata:
        """Parse a database row to CommandMetadata.

        Expected column order (15 fields):
            domain, command_id, command_type, status, attempts,
            max_attempts, msg_id, correlation_id, reply_queue,
            last_error_type, last_error_code, last_error_msg,
            created_at, updated_at, batch_id

        Args:
            row: Database row tuple

        Returns:
            CommandMetadata instance
        """
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

    @staticmethod
    def from_rows(rows: list[tuple[Any, ...]]) -> list[CommandMetadata]:
        """Parse multiple database rows to CommandMetadata list.

        Args:
            rows: List of database row tuples

        Returns:
            List of CommandMetadata instances
        """
        return [CommandParsers.from_row(row) for row in rows]
