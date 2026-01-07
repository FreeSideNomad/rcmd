"""E2E Application Models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Json


@dataclass
class BatchSummary:
    """Batch summary for reply queue aggregation."""

    id: int | None
    batch_id: UUID
    domain: str
    total_expected: int
    success_count: int
    failed_count: int
    canceled_count: int
    created_at: datetime | None = None
    completed_at: datetime | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "BatchSummary":
        """Create from database row."""
        return cls(
            id=row[0],
            batch_id=row[1],
            domain=row[2],
            total_expected=row[3],
            success_count=row[4],
            failed_count=row[5],
            canceled_count=row[6],
            created_at=row[7],
            completed_at=row[8],
        )

    @property
    def total_received(self) -> int:
        """Total replies received so far."""
        return self.success_count + self.failed_count + self.canceled_count

    @property
    def is_complete(self) -> bool:
        """Check if all expected replies have been received."""
        return self.total_received >= self.total_expected


@dataclass
class TestCommand:
    """Test command with behavior specification."""

    id: int | None
    command_id: UUID
    payload: dict[str, Any]
    behavior: dict[str, Any]
    created_at: datetime | None = None
    processed_at: datetime | None = None
    attempts: int = 0
    result: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "TestCommand":
        """Create from database row."""
        return cls(
            id=row[0],
            command_id=row[1],
            payload=row[2],
            behavior=row[3],
            created_at=row[4],
            processed_at=row[5],
            attempts=row[6],
            result=row[7],
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "command_id": str(self.command_id),
            "payload": self.payload,
            "behavior": self.behavior,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "attempts": self.attempts,
            "result": self.result,
        }


class TestCommandRepository:
    """Repository for test commands."""

    def __init__(self, pool: Any) -> None:
        """Initialize repository."""
        self.pool = pool

    async def create(
        self,
        command_id: UUID,
        behavior: dict[str, Any],
        payload: dict[str, Any] | None = None,
        conn: AsyncConnection[Any] | None = None,
    ) -> TestCommand:
        """Create a new test command."""
        if conn is not None:
            return await self._create_with_connection(conn, command_id, behavior, payload or {})

        async with self.pool.connection() as acquired_conn:
            return await self._create_with_connection(
                acquired_conn, command_id, behavior, payload or {}
            )

    async def _create_with_connection(
        self,
        conn: AsyncConnection[Any],
        command_id: UUID,
        behavior: dict[str, Any],
        payload: dict[str, Any],
    ) -> TestCommand:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO e2e.test_command (command_id, payload, behavior)
                VALUES (%s, %s, %s)
                RETURNING id, command_id, payload, behavior,
                          created_at, processed_at, attempts, result
                """,
                (command_id, Json(payload), Json(behavior)),
            )
            row = await cur.fetchone()
            return TestCommand.from_row(row)

    async def create_batch(
        self,
        commands: list[tuple[UUID, dict[str, Any], dict[str, Any]]],
    ) -> None:
        """Create multiple test commands in a single operation.

        Args:
            commands: List of (command_id, behavior, payload) tuples
        """
        if not commands:
            return

        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.executemany(
                """
                INSERT INTO e2e.test_command (command_id, payload, behavior)
                VALUES (%s, %s, %s)
                """,
                [(cmd_id, Json(payload), Json(behavior)) for cmd_id, behavior, payload in commands],
            )

    async def get_by_command_id(self, command_id: UUID) -> TestCommand | None:
        """Get test command by command_id."""
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, command_id, payload, behavior,
                       created_at, processed_at, attempts, result
                FROM e2e.test_command
                WHERE command_id = %s
                """,
                (command_id,),
            )
            row = await cur.fetchone()
            return TestCommand.from_row(row) if row else None

    async def increment_attempts(self, command_id: UUID) -> int:
        """Increment attempts and return new count."""
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE e2e.test_command
                SET attempts = attempts + 1
                WHERE command_id = %s
                RETURNING attempts
                """,
                (command_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else 0

    async def mark_processed(
        self,
        command_id: UUID,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Mark command as processed."""
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE e2e.test_command
                SET processed_at = NOW(), result = %s
                WHERE command_id = %s
                """,
                (Json(result) if result else None, command_id),
            )

    async def update_behavior(self, command_id: UUID, behavior: dict[str, Any]) -> None:
        """Update command behavior."""
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    UPDATE e2e.test_command
                    SET behavior = %s
                    WHERE command_id = %s
                    """,
                (Json(behavior), command_id),
            )

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[TestCommand]:
        """List all test commands."""
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, command_id, payload, behavior,
                       created_at, processed_at, attempts, result
                FROM e2e.test_command
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = await cur.fetchall()
            return [TestCommand.from_row(row) for row in rows]


class BatchSummaryRepository:
    """Repository for batch summary records."""

    def __init__(self, pool: Any) -> None:
        """Initialize repository."""
        self.pool = pool

    async def create(
        self,
        batch_id: UUID,
        total_expected: int,
        domain: str = "e2e",
    ) -> BatchSummary:
        """Create a new batch summary record."""
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO e2e.batch_summary (batch_id, domain, total_expected)
                VALUES (%s, %s, %s)
                RETURNING id, batch_id, domain, total_expected,
                          success_count, failed_count, canceled_count,
                          created_at, completed_at
                """,
                (batch_id, domain, total_expected),
            )
            row = await cur.fetchone()
            return BatchSummary.from_row(row)

    async def get_by_batch_id(self, batch_id: UUID) -> BatchSummary | None:
        """Get batch summary by batch_id."""
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, batch_id, domain, total_expected,
                       success_count, failed_count, canceled_count,
                       created_at, completed_at
                FROM e2e.batch_summary
                WHERE batch_id = %s
                """,
                (batch_id,),
            )
            row = await cur.fetchone()
            return BatchSummary.from_row(row) if row else None

    async def increment_success(self, batch_id: UUID) -> BatchSummary | None:
        """Increment success count and return updated summary."""
        return await self._increment_count(batch_id, "success_count")

    async def increment_failed(self, batch_id: UUID) -> BatchSummary | None:
        """Increment failed count and return updated summary."""
        return await self._increment_count(batch_id, "failed_count")

    async def increment_canceled(self, batch_id: UUID) -> BatchSummary | None:
        """Increment canceled count and return updated summary."""
        return await self._increment_count(batch_id, "canceled_count")

    async def _increment_count(self, batch_id: UUID, column: str) -> BatchSummary | None:
        """Increment a count column and mark complete if all received."""
        async with self.pool.connection() as conn, conn.cursor() as cur:
            # Update count and check if complete
            await cur.execute(
                f"""
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
                """,
                (batch_id,),
            )
            row = await cur.fetchone()
            return BatchSummary.from_row(row) if row else None

    async def delete(self, batch_id: UUID) -> bool:
        """Delete a batch summary record."""
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM e2e.batch_summary WHERE batch_id = %s",
                (batch_id,),
            )
            return cur.rowcount > 0
