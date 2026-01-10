"""SQL constants, parameter builders, and row parsers for batch operations.

This module extracts shared SQL logic for both async and sync implementations.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from commandbus.models import BatchMetadata, BatchStatus

if TYPE_CHECKING:
    from uuid import UUID


class BatchSQL:
    """SQL constants for batch operations."""

    # Column order for SELECT queries
    SELECT_COLUMNS = """
        domain, batch_id, name, custom_data, status,
        total_count, completed_count,
        canceled_count, in_troubleshooting_count,
        created_at, started_at, completed_at
    """

    SAVE = """
        INSERT INTO commandbus.batch (
            domain, batch_id, name, custom_data, status,
            total_count, completed_count,
            canceled_count, in_troubleshooting_count,
            created_at, started_at, completed_at
        ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    GET = f"""
        SELECT {SELECT_COLUMNS}
        FROM commandbus.batch
        WHERE domain = %s AND batch_id = %s
    """

    EXISTS = """
        SELECT EXISTS(
            SELECT 1 FROM commandbus.batch
            WHERE domain = %s AND batch_id = %s
        )
    """

    LIST = f"""
        SELECT {SELECT_COLUMNS}
        FROM commandbus.batch
        WHERE domain = %s
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """

    LIST_WITH_STATUS = f"""
        SELECT {SELECT_COLUMNS}
        FROM commandbus.batch
        WHERE domain = %s AND status = %s
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """

    # Stored procedure calls for TSQ operations
    SP_TSQ_COMPLETE = "SELECT commandbus.sp_tsq_complete(%s, %s)"
    SP_TSQ_CANCEL = "SELECT commandbus.sp_tsq_cancel(%s, %s)"
    SP_TSQ_RETRY = "SELECT commandbus.sp_tsq_retry(%s, %s)"

    # Stats refresh - calculates batch stats from command table on demand
    SP_REFRESH_STATS = "SELECT * FROM commandbus.sp_refresh_batch_stats(%s, %s)"


class BatchParams:
    """Static methods for building SQL parameter tuples."""

    @staticmethod
    def save(metadata: BatchMetadata) -> tuple[Any, ...]:
        """Build parameters for SAVE query.

        Args:
            metadata: Batch metadata to save

        Returns:
            Tuple of 12 parameters for SAVE SQL
        """
        custom_data_json = json.dumps(metadata.custom_data) if metadata.custom_data else None
        return (
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
        )

    @staticmethod
    def get(domain: str, batch_id: UUID) -> tuple[str, UUID]:
        """Build parameters for GET query."""
        return (domain, batch_id)

    @staticmethod
    def exists(domain: str, batch_id: UUID) -> tuple[str, UUID]:
        """Build parameters for EXISTS query."""
        return (domain, batch_id)

    @staticmethod
    def list_batches(
        domain: str,
        limit: int,
        offset: int,
    ) -> tuple[str, int, int]:
        """Build parameters for LIST query."""
        return (domain, limit, offset)

    @staticmethod
    def list_batches_with_status(
        domain: str,
        status: BatchStatus | str,
        limit: int,
        offset: int,
    ) -> tuple[str, str, int, int]:
        """Build parameters for LIST_WITH_STATUS query."""
        status_value = status.value if isinstance(status, BatchStatus) else status
        return (domain, status_value, limit, offset)

    @staticmethod
    def tsq_operation(domain: str, batch_id: UUID) -> tuple[str, UUID]:
        """Build parameters for TSQ stored procedure calls."""
        return (domain, batch_id)


class BatchParsers:
    """Static methods for parsing database rows to BatchMetadata."""

    @staticmethod
    def from_row(row: tuple[Any, ...]) -> BatchMetadata:
        """Parse a database row to BatchMetadata.

        Expected column order (12 fields):
            domain, batch_id, name, custom_data, status,
            total_count, completed_count,
            canceled_count, in_troubleshooting_count,
            created_at, started_at, completed_at

        Args:
            row: Database row tuple

        Returns:
            BatchMetadata instance
        """
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

    @staticmethod
    def from_rows(rows: list[tuple[Any, ...]]) -> list[BatchMetadata]:
        """Parse multiple database rows to BatchMetadata list.

        Args:
            rows: List of database row tuples

        Returns:
            List of BatchMetadata instances
        """
        return [BatchParsers.from_row(row) for row in rows]
