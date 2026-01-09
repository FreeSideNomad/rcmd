"""SQL constants, parameter builders, and row parsers for process operations.

This module extracts shared SQL logic for both async and sync implementations.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from commandbus.models import ReplyOutcome
from commandbus.process.models import (
    ProcessAuditEntry,
    ProcessMetadata,
    ProcessStatus,
)

if TYPE_CHECKING:
    from uuid import UUID


class ProcessSQL:
    """SQL constants for process operations."""

    # Column order for SELECT queries
    SELECT_COLUMNS = """
        domain, process_id, process_type, status, current_step,
        state, error_code, error_message,
        created_at, updated_at, completed_at
    """

    SAVE = """
        INSERT INTO commandbus.process (
            domain, process_id, process_type, status, current_step,
            state, error_code, error_message,
            created_at, updated_at, completed_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s
        )
    """

    UPDATE = """
        UPDATE commandbus.process SET
            status = %s,
            current_step = %s,
            state = %s,
            error_code = %s,
            error_message = %s,
            updated_at = NOW(),
            completed_at = %s
        WHERE domain = %s AND process_id = %s
    """

    GET_BY_ID = f"""
        SELECT {SELECT_COLUMNS}
        FROM commandbus.process
        WHERE domain = %s AND process_id = %s
    """

    FIND_BY_STATUS = f"""
        SELECT {SELECT_COLUMNS}
        FROM commandbus.process
        WHERE domain = %s AND status = ANY(%s)
    """

    # Audit table queries
    LOG_STEP = """
        INSERT INTO commandbus.process_audit (
            domain, process_id, step_name, command_id, command_type,
            command_data, sent_at, reply_outcome, reply_data, received_at
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
    """

    UPDATE_STEP_REPLY = """
        UPDATE commandbus.process_audit SET
            reply_outcome = %s,
            reply_data = %s,
            received_at = %s
        WHERE domain = %s AND process_id = %s AND command_id = %s
    """

    GET_AUDIT_TRAIL = """
        SELECT step_name, command_id, command_type, command_data,
               sent_at, reply_outcome, reply_data, received_at
        FROM commandbus.process_audit
        WHERE domain = %s AND process_id = %s
        ORDER BY sent_at ASC
    """

    GET_COMPLETED_STEPS = """
        SELECT step_name
        FROM commandbus.process_audit
        WHERE domain = %s AND process_id = %s AND reply_outcome = 'SUCCESS'
        ORDER BY sent_at ASC
    """


class ProcessParams:
    """Static methods for building SQL parameter tuples."""

    @staticmethod
    def save(process: ProcessMetadata[Any, Any], state_data: dict[str, Any]) -> tuple[Any, ...]:
        """Build parameters for SAVE query.

        Args:
            process: Process metadata to save
            state_data: Serialized state data (dict form)

        Returns:
            Tuple of 11 parameters for SAVE SQL
        """
        return (
            process.domain,
            process.process_id,
            process.process_type,
            process.status.value,
            process.current_step,
            json.dumps(state_data),
            process.error_code,
            process.error_message,
            process.created_at,
            process.updated_at,
            process.completed_at,
        )

    @staticmethod
    def update(process: ProcessMetadata[Any, Any], state_data: dict[str, Any]) -> tuple[Any, ...]:
        """Build parameters for UPDATE query.

        Args:
            process: Process metadata to update
            state_data: Serialized state data (dict form)

        Returns:
            Tuple of 8 parameters for UPDATE SQL
        """
        return (
            process.status.value,
            process.current_step,
            json.dumps(state_data),
            process.error_code,
            process.error_message,
            process.completed_at,
            process.domain,
            process.process_id,
        )

    @staticmethod
    def get_by_id(domain: str, process_id: UUID) -> tuple[str, UUID]:
        """Build parameters for GET_BY_ID query."""
        return (domain, process_id)

    @staticmethod
    def find_by_status(domain: str, statuses: list[ProcessStatus]) -> tuple[str, list[str]]:
        """Build parameters for FIND_BY_STATUS query."""
        status_values = [s.value for s in statuses]
        return (domain, status_values)

    @staticmethod
    def log_step(domain: str, process_id: UUID, entry: ProcessAuditEntry) -> tuple[Any, ...]:
        """Build parameters for LOG_STEP query.

        Args:
            domain: The domain
            process_id: The process ID
            entry: Audit entry to log

        Returns:
            Tuple of 10 parameters for LOG_STEP SQL
        """
        return (
            domain,
            process_id,
            entry.step_name,
            entry.command_id,
            entry.command_type,
            json.dumps(entry.command_data) if entry.command_data is not None else None,
            entry.sent_at,
            entry.reply_outcome.value if entry.reply_outcome else None,
            json.dumps(entry.reply_data) if entry.reply_data is not None else None,
            entry.received_at,
        )

    @staticmethod
    def update_step_reply(
        domain: str, process_id: UUID, command_id: UUID, entry: ProcessAuditEntry
    ) -> tuple[Any, ...]:
        """Build parameters for UPDATE_STEP_REPLY query."""
        return (
            entry.reply_outcome.value if entry.reply_outcome else None,
            json.dumps(entry.reply_data) if entry.reply_data is not None else None,
            entry.received_at,
            domain,
            process_id,
            command_id,
        )

    @staticmethod
    def get_audit_trail(domain: str, process_id: UUID) -> tuple[str, UUID]:
        """Build parameters for GET_AUDIT_TRAIL query."""
        return (domain, process_id)

    @staticmethod
    def get_completed_steps(domain: str, process_id: UUID) -> tuple[str, UUID]:
        """Build parameters for GET_COMPLETED_STEPS query."""
        return (domain, process_id)


class ProcessParsers:
    """Static methods for parsing database rows."""

    @staticmethod
    def from_row(row: tuple[Any, ...]) -> ProcessMetadata[Any, Any]:
        """Parse a database row to ProcessMetadata.

        Expected column order (11 fields):
            domain, process_id, process_type, status, current_step,
            state, error_code, error_message,
            created_at, updated_at, completed_at

        Args:
            row: Database row tuple

        Returns:
            ProcessMetadata instance
        """
        state = row[5]
        if isinstance(state, str):
            state = json.loads(state)

        return ProcessMetadata(
            domain=row[0],
            process_id=row[1],
            process_type=row[2],
            status=ProcessStatus(row[3]),
            current_step=row[4],
            state=state,
            error_code=row[6],
            error_message=row[7],
            created_at=row[8],
            updated_at=row[9],
            completed_at=row[10],
        )

    @staticmethod
    def from_rows(rows: list[tuple[Any, ...]]) -> list[ProcessMetadata[Any, Any]]:
        """Parse multiple database rows to ProcessMetadata list."""
        return [ProcessParsers.from_row(row) for row in rows]

    @staticmethod
    def audit_entry_from_row(row: tuple[Any, ...]) -> ProcessAuditEntry:
        """Parse a database row to ProcessAuditEntry.

        Expected column order (8 fields):
            step_name, command_id, command_type, command_data,
            sent_at, reply_outcome, reply_data, received_at

        Args:
            row: Database row tuple

        Returns:
            ProcessAuditEntry instance
        """
        command_data = row[3]
        if isinstance(command_data, str):
            command_data = json.loads(command_data)

        reply_data = row[6]
        if isinstance(reply_data, str):
            reply_data = json.loads(reply_data)

        return ProcessAuditEntry(
            step_name=row[0],
            command_id=row[1],
            command_type=row[2],
            command_data=command_data,
            sent_at=row[4],
            reply_outcome=ReplyOutcome(row[5]) if row[5] else None,
            reply_data=reply_data,
            received_at=row[7],
        )

    @staticmethod
    def audit_entries_from_rows(rows: list[tuple[Any, ...]]) -> list[ProcessAuditEntry]:
        """Parse multiple database rows to ProcessAuditEntry list."""
        return [ProcessParsers.audit_entry_from_row(row) for row in rows]
