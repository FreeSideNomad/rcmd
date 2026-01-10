"""Repository for batch metadata storage."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from commandbus.models import BatchMetadata, BatchStatus

if TYPE_CHECKING:
    from uuid import UUID

    from psycopg import AsyncConnection
    from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


class PostgresBatchRepository:
    """PostgreSQL implementation of batch repository."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        """Initialize the repository.

        Args:
            pool: psycopg async connection pool
        """
        self._pool = pool

    async def save(
        self,
        metadata: BatchMetadata,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Save batch metadata to the database.

        Args:
            metadata: Batch metadata to save
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._save(conn, metadata)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._save(acquired_conn, metadata)

    async def _save(
        self,
        conn: AsyncConnection[Any],
        metadata: BatchMetadata,
    ) -> None:
        """Save metadata using an existing connection."""
        custom_data_json = json.dumps(metadata.custom_data) if metadata.custom_data else None
        await conn.execute(
            """
            INSERT INTO commandbus.batch (
                domain, batch_id, name, custom_data, status,
                total_count, completed_count,
                canceled_count, in_troubleshooting_count,
                created_at, started_at, completed_at
            ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                metadata.domain,
                metadata.batch_id,
                metadata.name,
                custom_data_json,
                metadata.status.value,
                metadata.total_count,
                metadata.completed_count,
                metadata.canceled_count,
                metadata.in_troubleshooting_count,
                metadata.created_at,
                metadata.started_at,
                metadata.completed_at,
            ),
        )
        logger.debug(f"Saved batch metadata: {metadata.domain}.{metadata.batch_id}")

    async def get(
        self,
        domain: str,
        batch_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> BatchMetadata | None:
        """Get batch metadata by domain and batch_id.

        Args:
            domain: The domain
            batch_id: The batch ID
            conn: Optional connection (for transaction support)

        Returns:
            BatchMetadata if found, None otherwise
        """
        if conn is not None:
            return await self._get(conn, domain, batch_id)

        async with self._pool.connection() as acquired_conn:
            return await self._get(acquired_conn, domain, batch_id)

    async def _get(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        batch_id: UUID,
    ) -> BatchMetadata | None:
        """Get metadata using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT domain, batch_id, name, custom_data, status,
                       total_count, completed_count,
                       canceled_count, in_troubleshooting_count,
                       created_at, started_at, completed_at
                FROM commandbus.batch
                WHERE domain = %s AND batch_id = %s
                """,
                (domain, batch_id),
            )
            row = await cur.fetchone()

        if row is None:
            return None

        return self._row_to_metadata(row)

    async def exists(
        self,
        domain: str,
        batch_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> bool:
        """Check if a batch exists.

        Args:
            domain: The domain
            batch_id: The batch ID
            conn: Optional connection (for transaction support)

        Returns:
            True if batch exists, False otherwise
        """
        if conn is not None:
            return await self._exists(conn, domain, batch_id)

        async with self._pool.connection() as acquired_conn:
            return await self._exists(acquired_conn, domain, batch_id)

    async def _exists(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        batch_id: UUID,
    ) -> bool:
        """Check existence using an existing connection."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT EXISTS(
                    SELECT 1 FROM commandbus.batch
                    WHERE domain = %s AND batch_id = %s
                )
                """,
                (domain, batch_id),
            )
            row = await cur.fetchone()
            return bool(row[0]) if row else False

    async def list_batches(
        self,
        domain: str,
        *,
        status: BatchStatus | str | None = None,
        limit: int = 100,
        offset: int = 0,
        conn: AsyncConnection[Any] | None = None,
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
        if conn is not None:
            return await self._list_batches(conn, domain, status, limit, offset)

        async with self._pool.connection() as acquired_conn:
            return await self._list_batches(acquired_conn, domain, status, limit, offset)

    async def _list_batches(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        status: BatchStatus | str | None,
        limit: int,
        offset: int,
    ) -> list[BatchMetadata]:
        """List batches using an existing connection."""
        conditions = ["domain = %s"]
        params: list[Any] = [domain]

        if status is not None:
            status_value = status.value if isinstance(status, BatchStatus) else status
            conditions.append("status = %s")
            params.append(status_value)

        where_clause = " AND ".join(conditions)
        params.extend([limit, offset])

        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT domain, batch_id, name, custom_data, status,
                       total_count, completed_count,
                       canceled_count, in_troubleshooting_count,
                       created_at, started_at, completed_at
                FROM commandbus.batch
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = await cur.fetchall()

        return [self._row_to_metadata(row) for row in rows]

    def _row_to_metadata(self, row: tuple[Any, ...]) -> BatchMetadata:
        """Convert a database row to BatchMetadata."""
        custom_data = row[3]
        if isinstance(custom_data, str):
            custom_data = json.loads(custom_data)

        return BatchMetadata(
            domain=row[0],
            batch_id=row[1],
            name=row[2],
            custom_data=custom_data,
            status=BatchStatus(row[4]),
            total_count=row[5],
            completed_count=row[6],
            canceled_count=row[7],
            in_troubleshooting_count=row[8],
            created_at=row[9],
            started_at=row[10],
            completed_at=row[11],
        )

    # =========================================================================
    # Batch Status Tracking Methods (S042)
    # TSQ operations that call stored procedures and return is_batch_complete
    # Note: Batch start and command complete/tsq_move are now handled by
    # sp_receive_command and sp_finish_command respectively
    # =========================================================================

    async def tsq_complete(
        self,
        domain: str,
        batch_id: UUID,
        conn: AsyncConnection[Any] | None = None,
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
        if conn is not None:
            return await self._tsq_complete(conn, domain, batch_id)

        async with self._pool.connection() as acquired_conn:
            return await self._tsq_complete(acquired_conn, domain, batch_id)

    async def _tsq_complete(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        batch_id: UUID,
    ) -> bool:
        """TSQ complete using stored procedure."""
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT commandbus.sp_tsq_complete(%s, %s)",
                (domain, batch_id),
            )
            row = await cur.fetchone()
            is_complete = bool(row[0]) if row else False
            logger.debug(f"Batch {domain}.{batch_id} TSQ complete: is_batch_complete={is_complete}")
            return is_complete

    async def tsq_cancel(
        self,
        domain: str,
        batch_id: UUID,
        conn: AsyncConnection[Any] | None = None,
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
        if conn is not None:
            return await self._tsq_cancel(conn, domain, batch_id)

        async with self._pool.connection() as acquired_conn:
            return await self._tsq_cancel(acquired_conn, domain, batch_id)

    async def _tsq_cancel(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        batch_id: UUID,
    ) -> bool:
        """TSQ cancel using stored procedure."""
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT commandbus.sp_tsq_cancel(%s, %s)",
                (domain, batch_id),
            )
            row = await cur.fetchone()
            is_complete = bool(row[0]) if row else False
            logger.debug(f"Batch {domain}.{batch_id} TSQ cancel: is_batch_complete={is_complete}")
            return is_complete

    async def tsq_retry(
        self,
        domain: str,
        batch_id: UUID,
        conn: AsyncConnection[Any] | None = None,
    ) -> None:
        """Update batch when operator retries a command from TSQ.

        Decrements in_troubleshooting_count (command goes back to queue).
        Note: Retry never completes a batch.

        Args:
            domain: The domain
            batch_id: The batch ID
            conn: Optional connection (for transaction support)
        """
        if conn is not None:
            await self._tsq_retry(conn, domain, batch_id)
        else:
            async with self._pool.connection() as acquired_conn:
                await self._tsq_retry(acquired_conn, domain, batch_id)

    async def _tsq_retry(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        batch_id: UUID,
    ) -> None:
        """TSQ retry using stored procedure."""
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT commandbus.sp_tsq_retry(%s, %s)",
                (domain, batch_id),
            )
            logger.debug(f"Batch {domain}.{batch_id} TSQ retry processed")

    async def refresh_stats(
        self,
        domain: str,
        batch_id: UUID,
        conn: AsyncConnection[Any] | None = None,
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
            return await self._refresh_stats(conn, domain, batch_id)

        async with self._pool.connection() as acquired_conn:
            return await self._refresh_stats(acquired_conn, domain, batch_id)

    async def _refresh_stats(
        self,
        conn: AsyncConnection[Any],
        domain: str,
        batch_id: UUID,
    ) -> BatchMetadata | None:
        """Refresh stats using stored procedure and return updated batch."""
        async with conn.cursor() as cur:
            # Call the stored procedure to refresh stats
            await cur.execute(
                "SELECT * FROM commandbus.sp_refresh_batch_stats(%s, %s)",
                (domain, batch_id),
            )
            result = await cur.fetchone()

            if result is None:
                return None

            logger.debug(
                f"Batch {domain}.{batch_id} stats refreshed: "
                f"completed={result[0]}, canceled={result[1]}, tsq={result[2]}, "
                f"is_complete={result[3]}"
            )

        # Return the updated batch metadata
        return await self._get(conn, domain, batch_id)
