"""Unit tests for commandbus._core.batch_sql module."""

from datetime import datetime
from uuid import uuid4

import pytest

from commandbus._core.batch_sql import BatchParams, BatchParsers, BatchSQL
from commandbus.models import BatchMetadata, BatchStatus


class TestBatchSQL:
    """Tests for BatchSQL class."""

    def test_select_columns_defined(self) -> None:
        """SELECT_COLUMNS should contain expected column list."""
        assert "domain" in BatchSQL.SELECT_COLUMNS
        assert "batch_id" in BatchSQL.SELECT_COLUMNS
        assert "name" in BatchSQL.SELECT_COLUMNS
        assert "custom_data" in BatchSQL.SELECT_COLUMNS
        assert "status" in BatchSQL.SELECT_COLUMNS

    def test_save_sql_has_correct_placeholders(self) -> None:
        """SAVE SQL should have 12 placeholders."""
        assert BatchSQL.SAVE.count("%s") == 12

    def test_get_sql_has_placeholders(self) -> None:
        """GET SQL should have 2 placeholders for domain and batch_id."""
        assert BatchSQL.GET.count("%s") == 2

    def test_exists_sql_has_placeholders(self) -> None:
        """EXISTS SQL should have 2 placeholders."""
        assert BatchSQL.EXISTS.count("%s") == 2

    def test_list_sql_has_placeholders(self) -> None:
        """LIST SQL should have 3 placeholders."""
        assert BatchSQL.LIST.count("%s") == 3

    def test_list_with_status_sql_has_placeholders(self) -> None:
        """LIST_WITH_STATUS SQL should have 4 placeholders."""
        assert BatchSQL.LIST_WITH_STATUS.count("%s") == 4

    def test_sp_tsq_complete_has_placeholders(self) -> None:
        """SP_TSQ_COMPLETE SQL should have 2 placeholders."""
        assert BatchSQL.SP_TSQ_COMPLETE.count("%s") == 2

    def test_sp_tsq_cancel_has_placeholders(self) -> None:
        """SP_TSQ_CANCEL SQL should have 2 placeholders."""
        assert BatchSQL.SP_TSQ_CANCEL.count("%s") == 2

    def test_sp_tsq_retry_has_placeholders(self) -> None:
        """SP_TSQ_RETRY SQL should have 2 placeholders."""
        assert BatchSQL.SP_TSQ_RETRY.count("%s") == 2


class TestBatchParams:
    """Tests for BatchParams class."""

    @pytest.fixture
    def sample_metadata(self) -> BatchMetadata:
        """Create sample BatchMetadata for testing."""
        return BatchMetadata(
            domain="test",
            batch_id=uuid4(),
            name="Test Batch",
            custom_data={"key": "value"},
            status=BatchStatus.PENDING,
            total_count=10,
            completed_count=0,
            canceled_count=0,
            in_troubleshooting_count=0,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            started_at=None,
            completed_at=None,
        )

    def test_save_returns_correct_tuple_length(self, sample_metadata: BatchMetadata) -> None:
        """save() should return 12 parameters."""
        params = BatchParams.save(sample_metadata)
        assert len(params) == 12

    def test_save_returns_correct_values(self, sample_metadata: BatchMetadata) -> None:
        """save() should return values in correct order."""
        params = BatchParams.save(sample_metadata)

        assert params[0] == sample_metadata.domain
        assert params[1] == sample_metadata.batch_id
        assert params[2] == sample_metadata.name
        assert params[3] == '{"key": "value"}'  # JSON serialized
        assert params[4] == sample_metadata.status.value
        assert params[5] == sample_metadata.total_count
        assert params[6] == sample_metadata.completed_count
        assert params[7] == sample_metadata.canceled_count
        assert params[8] == sample_metadata.in_troubleshooting_count
        assert params[9] == sample_metadata.created_at
        assert params[10] == sample_metadata.started_at
        assert params[11] == sample_metadata.completed_at

    def test_save_handles_none_custom_data(self, sample_metadata: BatchMetadata) -> None:
        """save() should handle None custom_data."""
        sample_metadata.custom_data = None
        params = BatchParams.save(sample_metadata)
        assert params[3] is None

    def test_get_returns_correct_tuple(self) -> None:
        """get() should return 2 parameters."""
        batch_id = uuid4()
        params = BatchParams.get("test", batch_id)

        assert params == ("test", batch_id)

    def test_exists_returns_correct_tuple(self) -> None:
        """exists() should return 2 parameters."""
        batch_id = uuid4()
        params = BatchParams.exists("test", batch_id)

        assert params == ("test", batch_id)

    def test_list_batches_returns_correct_tuple(self) -> None:
        """list_batches() should return 3 parameters."""
        params = BatchParams.list_batches("test", 100, 0)

        assert params == ("test", 100, 0)

    def test_list_batches_with_status_returns_correct_tuple(self) -> None:
        """list_batches_with_status() should return 4 parameters."""
        params = BatchParams.list_batches_with_status("test", BatchStatus.PENDING, 100, 0)

        assert params == ("test", "PENDING", 100, 0)

    def test_list_batches_with_status_accepts_string(self) -> None:
        """list_batches_with_status() should accept string status."""
        params = BatchParams.list_batches_with_status("test", "COMPLETED", 50, 10)

        assert params == ("test", "COMPLETED", 50, 10)

    def test_tsq_operation_returns_correct_tuple(self) -> None:
        """tsq_operation() should return 2 parameters."""
        batch_id = uuid4()
        params = BatchParams.tsq_operation("test", batch_id)

        assert params == ("test", batch_id)


class TestBatchParsers:
    """Tests for BatchParsers class."""

    def test_from_row_creates_metadata(self) -> None:
        """from_row() should create BatchMetadata from tuple."""
        batch_id = uuid4()
        created_at = datetime(2024, 1, 1, 12, 0, 0)
        started_at = datetime(2024, 1, 1, 12, 1, 0)
        completed_at = datetime(2024, 1, 1, 12, 30, 0)

        row = (
            "test",  # domain
            batch_id,  # batch_id
            "Test Batch",  # name
            {"key": "value"},  # custom_data (already parsed dict)
            "COMPLETED",  # status
            10,  # total_count
            9,  # completed_count
            1,  # canceled_count
            0,  # in_troubleshooting_count
            created_at,  # created_at
            started_at,  # started_at
            completed_at,  # completed_at
        )

        metadata = BatchParsers.from_row(row)

        assert metadata.domain == "test"
        assert metadata.batch_id == batch_id
        assert metadata.name == "Test Batch"
        assert metadata.custom_data == {"key": "value"}
        assert metadata.status == BatchStatus.COMPLETED
        assert metadata.total_count == 10
        assert metadata.completed_count == 9
        assert metadata.canceled_count == 1
        assert metadata.in_troubleshooting_count == 0
        assert metadata.created_at == created_at
        assert metadata.started_at == started_at
        assert metadata.completed_at == completed_at

    def test_from_row_handles_string_custom_data(self) -> None:
        """from_row() should parse JSON string custom_data."""
        row = (
            "test",
            uuid4(),
            "Test Batch",
            '{"key": "value", "nested": {"a": 1}}',  # JSON string
            "PENDING",
            5,
            0,
            0,
            0,
            datetime.now(),
            None,
            None,
        )

        metadata = BatchParsers.from_row(row)

        assert metadata.custom_data == {"key": "value", "nested": {"a": 1}}

    def test_from_row_handles_none_custom_data(self) -> None:
        """from_row() should handle None custom_data."""
        row = (
            "test",
            uuid4(),
            None,
            None,  # None custom_data
            "PENDING",
            5,
            0,
            0,
            0,
            datetime.now(),
            None,
            None,
        )

        metadata = BatchParsers.from_row(row)
        assert metadata.custom_data is None

    def test_from_row_handles_all_statuses(self) -> None:
        """from_row() should handle all BatchStatus values."""
        for status in BatchStatus:
            row = (
                "test",
                uuid4(),
                "Test",
                None,
                status.value,
                10,
                0,
                0,
                0,
                datetime.now(),
                None,
                None,
            )

            metadata = BatchParsers.from_row(row)
            assert metadata.status == status

    def test_from_rows_creates_list(self) -> None:
        """from_rows() should create list of BatchMetadata."""
        rows = [
            (
                "test",
                uuid4(),
                "Batch 1",
                None,
                "PENDING",
                5,
                0,
                0,
                0,
                datetime.now(),
                None,
                None,
            ),
            (
                "test",
                uuid4(),
                "Batch 2",
                None,
                "COMPLETED",
                10,
                10,
                0,
                0,
                datetime.now(),
                datetime.now(),
                datetime.now(),
            ),
        ]

        metadata_list = BatchParsers.from_rows(rows)

        assert len(metadata_list) == 2
        assert metadata_list[0].name == "Batch 1"
        assert metadata_list[1].name == "Batch 2"

    def test_from_rows_handles_empty_list(self) -> None:
        """from_rows() should handle empty list."""
        metadata_list = BatchParsers.from_rows([])
        assert metadata_list == []
