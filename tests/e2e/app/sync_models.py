"""Synchronous E2E Application Models and Repositories."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.types.json import Json

from .models import BatchSummary, TestCommand

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg import Connection
    from psycopg_pool import ConnectionPool


class SyncTestCommandRepository:
    """Synchronous repository for test commands."""

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        """Initialize repository with sync connection pool."""
        self._pool = pool

    def get_by_command_id(
        self,
        command_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> TestCommand | None:
        """Get test command by command_id."""
        sql = """
            SELECT id, command_id, payload, behavior,
                   created_at, processed_at, attempts, result
            FROM e2e.test_command
            WHERE command_id = %s
        """
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, (command_id,))
                row = cur.fetchone()
                return TestCommand.from_row(row) if row else None

        with self._pool.connection() as acquired_conn, acquired_conn.cursor() as cur:
            cur.execute(sql, (command_id,))
            row = cur.fetchone()
            return TestCommand.from_row(row) if row else None

    def increment_attempts(
        self,
        command_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> int:
        """Increment attempts and return new count."""
        sql = """
            UPDATE e2e.test_command
            SET attempts = attempts + 1
            WHERE command_id = %s
            RETURNING attempts
        """
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, (command_id,))
                row = cur.fetchone()
                return row[0] if row else 0

        with self._pool.connection() as acquired_conn, acquired_conn.cursor() as cur:
            cur.execute(sql, (command_id,))
            row = cur.fetchone()
            return row[0] if row else 0

    def mark_processed(
        self,
        command_id: UUID,
        result: dict[str, Any] | None = None,
        conn: Connection[Any] | None = None,
    ) -> None:
        """Mark command as processed."""
        sql = """
            UPDATE e2e.test_command
            SET processed_at = NOW(), result = %s
            WHERE command_id = %s
        """
        params = (Json(result) if result else None, command_id)

        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            return

        with self._pool.connection() as acquired_conn, acquired_conn.cursor() as cur:
            cur.execute(sql, params)


class SyncBatchSummaryRepository:
    """Synchronous repository for batch summary records."""

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        """Initialize repository with sync connection pool."""
        self._pool = pool

    def get_by_batch_id(
        self,
        batch_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> BatchSummary | None:
        """Get batch summary by batch_id."""
        sql = """
            SELECT id, batch_id, domain, total_expected,
                   success_count, failed_count, canceled_count,
                   created_at, completed_at
            FROM e2e.batch_summary
            WHERE batch_id = %s
        """
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, (batch_id,))
                row = cur.fetchone()
                return BatchSummary.from_row(row) if row else None

        with self._pool.connection() as acquired_conn, acquired_conn.cursor() as cur:
            cur.execute(sql, (batch_id,))
            row = cur.fetchone()
            return BatchSummary.from_row(row) if row else None

    def increment_success(
        self,
        batch_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> BatchSummary | None:
        """Increment success count and return updated summary."""
        return self._increment_count(batch_id, "success_count", conn)

    def increment_failed(
        self,
        batch_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> BatchSummary | None:
        """Increment failed count and return updated summary."""
        return self._increment_count(batch_id, "failed_count", conn)

    def increment_canceled(
        self,
        batch_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> BatchSummary | None:
        """Increment canceled count and return updated summary."""
        return self._increment_count(batch_id, "canceled_count", conn)

    def _increment_count(
        self,
        batch_id: UUID,
        column: str,
        conn: Connection[Any] | None = None,
    ) -> BatchSummary | None:
        """Increment a count column and mark complete if all received."""
        sql = f"""
            UPDATE e2e.batch_summary
            SET {column} = {column} + 1,
                completed_at = CASE
                    WHEN success_count + failed_count + canceled_count + 1 >= total_expected
                    THEN NOW()
                    ELSE completed_at
                END
            WHERE batch_id = %s
            RETURNING id, batch_id, domain, total_expected,
                      success_count, failed_count, canceled_count,
                      created_at, completed_at
        """
        if conn is not None:
            with conn.cursor() as cur:
                cur.execute(sql, (batch_id,))
                row = cur.fetchone()
                return BatchSummary.from_row(row) if row else None

        with self._pool.connection() as acquired_conn, acquired_conn.cursor() as cur:
            cur.execute(sql, (batch_id,))
            row = cur.fetchone()
            return BatchSummary.from_row(row) if row else None
