"""Native synchronous process repository.

This module provides a synchronous process repository using psycopg3's
thread-safe ConnectionPool for native sync operations without
async wrapper overhead.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from commandbus._core.process_sql import ProcessParams, ProcessParsers, ProcessSQL

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg import Connection
    from psycopg_pool import ConnectionPool

    from commandbus.process.models import (
        ProcessAuditEntry,
        ProcessMetadata,
        ProcessStatus,
    )

logger = logging.getLogger(__name__)


class SyncProcessRepository:
    """Synchronous process repository using native sync connections.

    This repository provides sync methods for process metadata persistence,
    using psycopg3's thread-safe ConnectionPool. Each method accepts an
    optional connection parameter for transaction support.

    Example:
        pool = ConnectionPool(conninfo=DATABASE_URL)
        repo = SyncProcessRepository(pool)

        # Save a process
        repo.save(process)

        # Get process by ID
        process = repo.get_by_id(domain, process_id)

        # Log a step
        repo.log_step(domain, process_id, entry)
    """

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        """Initialize the sync process repository.

        Args:
            pool: psycopg sync connection pool
        """
        self._pool = pool

    def save(
        self,
        process: ProcessMetadata[Any, Any],
        conn: Connection[Any] | None = None,
    ) -> None:
        """Save a new process to the database.

        Args:
            process: Process metadata to save
            conn: Optional connection (for transaction support)
        """
        state_data = process.state
        if hasattr(state_data, "to_dict"):
            state_data = state_data.to_dict()

        sql = ProcessSQL.SAVE
        params = ProcessParams.save(process, state_data)

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

        logger.debug("Saved process: %s.%s", process.domain, process.process_id)

    def update(
        self,
        process: ProcessMetadata[Any, Any],
        conn: Connection[Any] | None = None,
    ) -> None:
        """Update an existing process.

        Args:
            process: Process metadata to update
            conn: Optional connection (for transaction support)
        """
        state_data = process.state
        if hasattr(state_data, "to_dict"):
            state_data = state_data.to_dict()

        sql = ProcessSQL.UPDATE
        params = ProcessParams.update(process, state_data)

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

        logger.debug("Updated process: %s.%s", process.domain, process.process_id)

    def get_by_id(
        self,
        domain: str,
        process_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> ProcessMetadata[Any, Any] | None:
        """Get process by domain and process_id.

        Args:
            domain: The domain
            process_id: The process ID
            conn: Optional connection (for transaction support)

        Returns:
            ProcessMetadata if found, None otherwise
        """
        sql = ProcessSQL.GET_BY_ID
        params = ProcessParams.get_by_id(domain, process_id)

        if conn is not None:
            return self._get_by_id_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._get_by_id_with_conn(c, sql, params)

    def _get_by_id_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, UUID],
    ) -> ProcessMetadata[Any, Any] | None:
        """Get process using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()

        if row is None:
            return None

        return ProcessParsers.from_row(row)

    def find_by_status(
        self,
        domain: str,
        statuses: list[ProcessStatus],
        conn: Connection[Any] | None = None,
    ) -> list[ProcessMetadata[Any, Any]]:
        """Find processes by status.

        Args:
            domain: The domain
            statuses: List of statuses to filter by
            conn: Optional connection (for transaction support)

        Returns:
            List of ProcessMetadata matching the statuses
        """
        sql = ProcessSQL.FIND_BY_STATUS
        params = ProcessParams.find_by_status(domain, statuses)

        if conn is not None:
            return self._find_by_status_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._find_by_status_with_conn(c, sql, params)

    def _find_by_status_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, list[str]],
    ) -> list[ProcessMetadata[Any, Any]]:
        """Find processes using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return ProcessParsers.from_rows(rows)

    def log_step(
        self,
        domain: str,
        process_id: UUID,
        entry: ProcessAuditEntry,
        conn: Connection[Any] | None = None,
    ) -> None:
        """Log a step execution to audit trail.

        Args:
            domain: The domain
            process_id: The process ID
            entry: Audit entry to log
            conn: Optional connection (for transaction support)
        """
        sql = ProcessSQL.LOG_STEP
        params = ProcessParams.log_step(domain, process_id, entry)

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

        logger.debug("Logged step %s for process %s.%s", entry.step_name, domain, process_id)

    def update_step_reply(
        self,
        domain: str,
        process_id: UUID,
        command_id: UUID,
        entry: ProcessAuditEntry,
        conn: Connection[Any] | None = None,
    ) -> None:
        """Update step with reply information.

        Args:
            domain: The domain
            process_id: The process ID
            command_id: The command ID of the step
            entry: Audit entry with reply data
            conn: Optional connection (for transaction support)
        """
        sql = ProcessSQL.UPDATE_STEP_REPLY
        params = ProcessParams.update_step_reply(domain, process_id, command_id, entry)

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

        logger.debug(
            "Updated step reply for command %s in process %s.%s",
            command_id,
            domain,
            process_id,
        )

    def get_audit_trail(
        self,
        domain: str,
        process_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> list[ProcessAuditEntry]:
        """Get full audit trail for a process.

        Args:
            domain: The domain
            process_id: The process ID
            conn: Optional connection (for transaction support)

        Returns:
            List of ProcessAuditEntry ordered by sent_at ascending
        """
        sql = ProcessSQL.GET_AUDIT_TRAIL
        params = ProcessParams.get_audit_trail(domain, process_id)

        if conn is not None:
            return self._get_audit_trail_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._get_audit_trail_with_conn(c, sql, params)

    def _get_audit_trail_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, UUID],
    ) -> list[ProcessAuditEntry]:
        """Get audit trail using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return ProcessParsers.audit_entries_from_rows(rows)

    def get_completed_steps(
        self,
        domain: str,
        process_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> list[str]:
        """Get list of completed step names (for compensation).

        Args:
            domain: The domain
            process_id: The process ID
            conn: Optional connection (for transaction support)

        Returns:
            List of step names that completed successfully
        """
        sql = ProcessSQL.GET_COMPLETED_STEPS
        params = ProcessParams.get_completed_steps(domain, process_id)

        if conn is not None:
            return self._get_completed_steps_with_conn(conn, sql, params)
        else:
            with self._pool.connection() as c:
                return self._get_completed_steps_with_conn(c, sql, params)

    def _get_completed_steps_with_conn(
        self,
        conn: Connection[Any],
        sql: str,
        params: tuple[str, UUID],
    ) -> list[str]:
        """Get completed steps using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return [row[0] for row in rows]
