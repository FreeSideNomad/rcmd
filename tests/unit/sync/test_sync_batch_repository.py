"""Unit tests for commandbus.sync.repositories.batch module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from commandbus._core.batch_sql import BatchSQL
from commandbus.models import BatchMetadata, BatchStatus
from commandbus.sync.repositories.batch import SyncBatchRepository


def make_batch_metadata(
    domain: str = "test_domain",
    batch_id=None,
    status: BatchStatus = BatchStatus.PENDING,
    total_count: int = 10,
    completed_count: int = 0,
    name: str | None = "Test Batch",
    custom_data: dict | None = None,
) -> BatchMetadata:
    """Create a BatchMetadata for testing."""
    now = datetime.now(UTC)
    return BatchMetadata(
        domain=domain,
        batch_id=batch_id or uuid4(),
        status=status,
        name=name,
        custom_data=custom_data,
        total_count=total_count,
        completed_count=completed_count,
        canceled_count=0,
        in_troubleshooting_count=0,
        created_at=now,
        started_at=None,
        completed_at=None,
    )


def make_row_from_metadata(metadata: BatchMetadata) -> tuple:
    """Create a database row tuple from BatchMetadata.

    Row format matches BatchParsers.from_row expectations (13 fields):
        domain, batch_id, name, custom_data, status,
        total_count, completed_count, failed_count,
        canceled_count, in_troubleshooting_count,
        created_at, started_at, completed_at
    """
    return (
        metadata.domain,
        metadata.batch_id,
        metadata.name,
        metadata.custom_data,
        metadata.status.value,
        metadata.total_count,
        metadata.completed_count,
        metadata.failed_count,
        metadata.canceled_count,
        metadata.in_troubleshooting_count,
        metadata.created_at,
        metadata.started_at,
        metadata.completed_at,
    )


class TestSyncBatchRepositoryInit:
    """Tests for SyncBatchRepository initialization."""

    def test_init_stores_pool(self) -> None:
        """SyncBatchRepository should store the pool reference."""
        pool = MagicMock()
        repo = SyncBatchRepository(pool)
        assert repo._pool is pool


class TestSyncBatchRepositorySave:
    """Tests for SyncBatchRepository.save method."""

    def test_save_with_pool(self) -> None:
        """save should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        metadata = make_batch_metadata()
        repo.save(metadata)

        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert args[0][0] == BatchSQL.SAVE

    def test_save_with_provided_connection(self) -> None:
        """save should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncBatchRepository(pool)
        metadata = make_batch_metadata()
        repo.save(metadata, conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_save_passes_correct_parameters(self) -> None:
        """save should pass correct parameters to SQL."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        metadata = make_batch_metadata(domain="my_domain")
        repo.save(metadata)

        args = conn.execute.call_args[0][1]
        assert args[0] == "my_domain"  # domain is first param


class TestSyncBatchRepositoryGet:
    """Tests for SyncBatchRepository.get method."""

    def test_get_returns_metadata_when_found(self) -> None:
        """get should return BatchMetadata when found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        metadata = make_batch_metadata()
        cursor.fetchone.return_value = make_row_from_metadata(metadata)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.get("test_domain", metadata.batch_id)

        assert result is not None
        assert result.batch_id == metadata.batch_id

    def test_get_returns_none_when_not_found(self) -> None:
        """get should return None when batch not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.get("domain", uuid4())

        assert result is None

    def test_get_with_provided_connection(self) -> None:
        """get should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncBatchRepository(pool)
        repo.get("domain", uuid4(), conn=conn)

        pool.connection.assert_not_called()

    def test_get_executes_correct_sql(self) -> None:
        """get should execute GET SQL with correct parameters."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        batch_id = uuid4()
        repo.get("my_domain", batch_id)

        args = cursor.execute.call_args
        assert args[0][0] == BatchSQL.GET
        assert args[0][1] == ("my_domain", batch_id)


class TestSyncBatchRepositoryExists:
    """Tests for SyncBatchRepository.exists method."""

    def test_exists_returns_true_when_found(self) -> None:
        """exists should return True when batch exists."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.exists("domain", uuid4())

        assert result is True

    def test_exists_returns_false_when_not_found(self) -> None:
        """exists should return False when batch not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.exists("domain", uuid4())

        assert result is False

    def test_exists_returns_false_on_no_row(self) -> None:
        """exists should return False when no row returned."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.exists("domain", uuid4())

        assert result is False

    def test_exists_with_provided_connection(self) -> None:
        """exists should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncBatchRepository(pool)
        repo.exists("domain", uuid4(), conn=conn)

        pool.connection.assert_not_called()

    def test_exists_executes_correct_sql(self) -> None:
        """exists should execute EXISTS SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        batch_id = uuid4()
        repo.exists("my_domain", batch_id)

        args = cursor.execute.call_args
        assert args[0][0] == BatchSQL.EXISTS


class TestSyncBatchRepositoryListBatches:
    """Tests for SyncBatchRepository.list_batches method."""

    def test_list_batches_returns_metadata_list(self) -> None:
        """list_batches should return list of BatchMetadata."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        metadata1 = make_batch_metadata()
        metadata2 = make_batch_metadata()
        cursor.fetchall.return_value = [
            make_row_from_metadata(metadata1),
            make_row_from_metadata(metadata2),
        ]
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.list_batches("domain")

        assert len(result) == 2
        assert all(isinstance(m, BatchMetadata) for m in result)

    def test_list_batches_empty_result(self) -> None:
        """list_batches should return empty list when no batches found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.list_batches("domain")

        assert result == []

    def test_list_batches_with_status_filter(self) -> None:
        """list_batches should use status filter SQL when provided."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        repo.list_batches("domain", status=BatchStatus.IN_PROGRESS)

        args = cursor.execute.call_args
        assert args[0][0] == BatchSQL.LIST_WITH_STATUS

    def test_list_batches_with_string_status(self) -> None:
        """list_batches should accept string status."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        repo.list_batches("domain", status="IN_PROGRESS")

        args = cursor.execute.call_args
        assert args[0][0] == BatchSQL.LIST_WITH_STATUS

    def test_list_batches_without_status_filter(self) -> None:
        """list_batches should use regular SQL when no status provided."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        repo.list_batches("domain")

        args = cursor.execute.call_args
        assert args[0][0] == BatchSQL.LIST

    def test_list_batches_with_limit_and_offset(self) -> None:
        """list_batches should pass limit and offset to SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        repo.list_batches("domain", limit=50, offset=10)

        args = cursor.execute.call_args[0][1]
        assert args[1] == 50  # limit
        assert args[2] == 10  # offset

    def test_list_batches_with_provided_connection(self) -> None:
        """list_batches should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncBatchRepository(pool)
        repo.list_batches("domain", conn=conn)

        pool.connection.assert_not_called()


class TestSyncBatchRepositoryTsqComplete:
    """Tests for SyncBatchRepository.tsq_complete method."""

    def test_tsq_complete_returns_true_when_batch_complete(self) -> None:
        """tsq_complete should return True when batch is complete."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.tsq_complete("domain", uuid4())

        assert result is True

    def test_tsq_complete_returns_false_when_batch_not_complete(self) -> None:
        """tsq_complete should return False when batch not complete."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.tsq_complete("domain", uuid4())

        assert result is False

    def test_tsq_complete_returns_false_on_no_row(self) -> None:
        """tsq_complete should return False when no row returned."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.tsq_complete("domain", uuid4())

        assert result is False

    def test_tsq_complete_with_provided_connection(self) -> None:
        """tsq_complete should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncBatchRepository(pool)
        repo.tsq_complete("domain", uuid4(), conn=conn)

        pool.connection.assert_not_called()

    def test_tsq_complete_executes_correct_sql(self) -> None:
        """tsq_complete should execute SP_TSQ_COMPLETE SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        batch_id = uuid4()
        repo.tsq_complete("my_domain", batch_id)

        args = cursor.execute.call_args
        assert args[0][0] == BatchSQL.SP_TSQ_COMPLETE
        assert args[0][1] == ("my_domain", batch_id)


class TestSyncBatchRepositoryTsqCancel:
    """Tests for SyncBatchRepository.tsq_cancel method."""

    def test_tsq_cancel_returns_true_when_batch_complete(self) -> None:
        """tsq_cancel should return True when batch is complete."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.tsq_cancel("domain", uuid4())

        assert result is True

    def test_tsq_cancel_returns_false_when_batch_not_complete(self) -> None:
        """tsq_cancel should return False when batch not complete."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.tsq_cancel("domain", uuid4())

        assert result is False

    def test_tsq_cancel_returns_false_on_no_row(self) -> None:
        """tsq_cancel should return False when no row returned."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        result = repo.tsq_cancel("domain", uuid4())

        assert result is False

    def test_tsq_cancel_with_provided_connection(self) -> None:
        """tsq_cancel should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncBatchRepository(pool)
        repo.tsq_cancel("domain", uuid4(), conn=conn)

        pool.connection.assert_not_called()

    def test_tsq_cancel_executes_correct_sql(self) -> None:
        """tsq_cancel should execute SP_TSQ_CANCEL SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        batch_id = uuid4()
        repo.tsq_cancel("my_domain", batch_id)

        args = cursor.execute.call_args
        assert args[0][0] == BatchSQL.SP_TSQ_CANCEL
        assert args[0][1] == ("my_domain", batch_id)


class TestSyncBatchRepositoryTsqRetry:
    """Tests for SyncBatchRepository.tsq_retry method."""

    def test_tsq_retry_with_pool(self) -> None:
        """tsq_retry should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        repo.tsq_retry("domain", uuid4())

        cursor.execute.assert_called_once()

    def test_tsq_retry_with_provided_connection(self) -> None:
        """tsq_retry should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncBatchRepository(pool)
        repo.tsq_retry("domain", uuid4(), conn=conn)

        cursor.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_tsq_retry_executes_correct_sql(self) -> None:
        """tsq_retry should execute SP_TSQ_RETRY SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncBatchRepository(pool)
        batch_id = uuid4()
        repo.tsq_retry("my_domain", batch_id)

        args = cursor.execute.call_args
        assert args[0][0] == BatchSQL.SP_TSQ_RETRY
        assert args[0][1] == ("my_domain", batch_id)


class TestSyncBatchRepositoryTransactionSupport:
    """Tests for transaction support across all methods."""

    def test_all_optional_conn_methods_support_provided_connection(self) -> None:
        """All methods with optional conn should accept and use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncBatchRepository(pool)
        metadata = make_batch_metadata()

        # Methods that use conn.execute directly
        repo.save(metadata, conn=conn)

        # Methods that use cursor but return None is fine
        repo.get("domain", uuid4(), conn=conn)

        # For exists, we need a boolean tuple
        cursor.fetchone.return_value = (True,)
        repo.exists("domain", uuid4(), conn=conn)

        # For TSQ operations
        cursor.fetchone.return_value = (False,)
        repo.tsq_complete("domain", uuid4(), conn=conn)
        repo.tsq_cancel("domain", uuid4(), conn=conn)
        repo.tsq_retry("domain", uuid4(), conn=conn)

        # list_batches uses fetchall
        repo.list_batches("domain", conn=conn)

        # Pool should never be accessed
        pool.connection.assert_not_called()
