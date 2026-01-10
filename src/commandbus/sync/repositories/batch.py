"""Native synchronous batch repository.

This module provides a synchronous batch repository using psycopg3's
thread-safe ConnectionPool for native sync operations without
async wrapper overhead.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from commandbus._core.batch_sql import BatchParams, BatchParsers, BatchSQL

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg import Connection
    from psycopg_pool import ConnectionPool

    from commandbus.models import BatchMetadata, BatchStatus

logger = logging.getLogger(__name__)


class SyncBatchRepository:
    """Synchronous batch repository using native sync connections.

    This repository provides sync methods for batch metadata persistence,
    using psycopg3's thread-safe ConnectionPool. Each method accepts an
    optional connection parameter for transaction support.

    Example:
        pool = ConnectionPool(conninfo=DATABASE_URL)
        repo = SyncBatchRepository(pool)

        # Save batch metadata
        repo.save(metadata)

        # Get batch by ID
        batch = repo.get(domain, batch_id)

        # List batches
        batches = repo.list_batches(domain, status=BatchStatus.IN_PROGRESS)
    """

    def __init__(self, pool: ConnectionPool[Any]) -> None:
        """Initialize the sync batch repository.

        Args:
            pool: psycopg sync connection pool
        """
        self._pool = pool

    def save(
        self,
        metadata: BatchMetadata,
        conn: Connection[Any] | None = None,
    ) -> None:
        """Save batch metadata to the database.

        Args:
            metadata: Batch metadata to save
            conn: Optional connection (for transaction support)
        """
        sql = BatchSQL.SAVE
        params = BatchParams.save(metadata)

        if conn is not None:
            conn.execute(sql, params)
        else:
            with self._pool.connection() as c:
                c.execute(sql, params)

        logger.debug("Saved batch metadata: %s.%s", metadata.domain, metadata.batch_id)

    def get(
        self,
        domain: str,
        batch_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> BatchMetadata | None:
        """Get batch metadata by domain and batch_id.

        Args:
            domain: The domain
            batch_id: The batch ID
            conn: Optional connection (for transaction support)

        Returns:
            BatchMetadata if found, None otherwise
        """
        sql = BatchSQL.GET
        params = BatchParams.get(domain, batch_id)

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
    ) -> BatchMetadata | None:
        """Get batch using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()

        if row is None:
            return None

        return BatchParsers.from_row(row)

    def exists(
        self,
        domain: str,
        batch_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> bool:
        """Check if a batch exists.

        Args:
            domain: The domain
            batch_id: The batch ID
            conn: Optional connection (for transaction support)

        Returns:
            True if batch exists, False otherwise
        """
        sql = BatchSQL.EXISTS
        params = BatchParams.exists(domain, batch_id)

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

    def list_batches(
        self,
        domain: str,
        *,
        status: BatchStatus | str | None = None,
        limit: int = 100,
        offset: int = 0,
        conn: Connection[Any] | None = None,
    ) -> list[BatchMetadata]:
        """List batches for a domain.

        Args:
            domain: The domain to list batches for
            status: Optional status filter
            limit: Maximum number of batches to return (default 100)
            offset: Number of batches to skip (default 0)
            conn: Optional connection (for transaction support)

        Returns:
            List of BatchMetadata ordered by created_at descending
        """
        if status is not None:
            sql = BatchSQL.LIST_WITH_STATUS
            params: tuple[Any, ...] = BatchParams.list_batches_with_status(
                domain, status, limit, offset
            )
        else:
            sql = BatchSQL.LIST
            params = BatchParams.list_batches(domain, limit, offset)

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
    ) -> list[BatchMetadata]:
        """List batches using an existing connection."""
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return BatchParsers.from_rows(rows)

    # =========================================================================
    # TSQ (Troubleshooting Queue) Operations
    # =========================================================================

    def tsq_complete(
        self,
        domain: str,
        batch_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> bool:
        """Update batch when operator completes a command from TSQ.

        Decrements in_troubleshooting_count, increments completed_count,
        and checks if batch is now complete.

        Args:
            domain: The domain
            batch_id: The batch ID
            conn: Optional connection (for transaction support)

        Returns:
            True if batch is now complete (for callback triggering)
        """
        params = BatchParams.tsq_operation(domain, batch_id)

        if conn is not None:
            return self._tsq_complete_with_conn(conn, params)
        else:
            with self._pool.connection() as c:
                return self._tsq_complete_with_conn(c, params)

    def _tsq_complete_with_conn(
        self,
        conn: Connection[Any],
        params: tuple[str, UUID],
    ) -> bool:
        """TSQ complete using stored procedure."""
        with conn.cursor() as cur:
            cur.execute(BatchSQL.SP_TSQ_COMPLETE, params)
            row = cur.fetchone()
            is_complete = bool(row[0]) if row else False

        logger.debug(
            "Batch %s.%s TSQ complete: is_batch_complete=%s",
            params[0],
            params[1],
            is_complete,
        )
        return is_complete

    def tsq_cancel(
        self,
        domain: str,
        batch_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> bool:
        """Update batch when operator cancels a command from TSQ.

        Decrements in_troubleshooting_count, increments canceled_count,
        and checks if batch is now complete.

        Args:
            domain: The domain
            batch_id: The batch ID
            conn: Optional connection (for transaction support)

        Returns:
            True if batch is now complete (for callback triggering)
        """
        params = BatchParams.tsq_operation(domain, batch_id)

        if conn is not None:
            return self._tsq_cancel_with_conn(conn, params)
        else:
            with self._pool.connection() as c:
                return self._tsq_cancel_with_conn(c, params)

    def _tsq_cancel_with_conn(
        self,
        conn: Connection[Any],
        params: tuple[str, UUID],
    ) -> bool:
        """TSQ cancel using stored procedure."""
        with conn.cursor() as cur:
            cur.execute(BatchSQL.SP_TSQ_CANCEL, params)
            row = cur.fetchone()
            is_complete = bool(row[0]) if row else False

        logger.debug(
            "Batch %s.%s TSQ cancel: is_batch_complete=%s",
            params[0],
            params[1],
            is_complete,
        )
        return is_complete

    def tsq_retry(
        self,
        domain: str,
        batch_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> None:
        """Update batch when operator retries a command from TSQ.

        Decrements in_troubleshooting_count (command goes back to queue).
        Note: Retry never completes a batch.

        Args:
            domain: The domain
            batch_id: The batch ID
            conn: Optional connection (for transaction support)
        """
        params = BatchParams.tsq_operation(domain, batch_id)

        if conn is not None:
            self._tsq_retry_with_conn(conn, params)
        else:
            with self._pool.connection() as c:
                self._tsq_retry_with_conn(c, params)

    def _tsq_retry_with_conn(
        self,
        conn: Connection[Any],
        params: tuple[str, UUID],
    ) -> None:
        """TSQ retry using stored procedure."""
        with conn.cursor() as cur:
            cur.execute(BatchSQL.SP_TSQ_RETRY, params)

        logger.debug("Batch %s.%s TSQ retry processed", params[0], params[1])

    # =========================================================================
    # Stats Refresh Operations
    # =========================================================================

    def refresh_stats(
        self,
        domain: str,
        batch_id: UUID,
        conn: Connection[Any] | None = None,
    ) -> BatchMetadata | None:
        """Refresh batch stats by calculating from command table.

        This calls sp_refresh_batch_stats which counts commands by status
        and updates the batch table with the calculated values.

        Args:
            domain: The domain
            batch_id: The batch ID
            conn: Optional connection (for transaction support)

        Returns:
            Updated BatchMetadata if found, None otherwise
        """
        if conn is not None:
            return self._refresh_stats_with_conn(conn, domain, batch_id)
        else:
            with self._pool.connection() as c:
                return self._refresh_stats_with_conn(c, domain, batch_id)

    def _refresh_stats_with_conn(
        self,
        conn: Connection[Any],
        domain: str,
        batch_id: UUID,
    ) -> BatchMetadata | None:
        """Refresh stats using stored procedure and return updated batch."""
        with conn.cursor() as cur:
            # Call the stored procedure to refresh stats
            cur.execute(BatchSQL.SP_REFRESH_STATS, (domain, batch_id))
            result = cur.fetchone()

            if result is None:
                return None

            logger.debug(
                "Batch %s.%s stats refreshed: completed=%s, canceled=%s, tsq=%s, is_complete=%s",
                domain,
                batch_id,
                result[0],
                result[1],
                result[2],
                result[3],
            )

        # Return the updated batch metadata
        return self._get_with_conn(conn, BatchSQL.GET, (domain, batch_id))
