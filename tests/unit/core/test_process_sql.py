"""Unit tests for commandbus._core.process_sql module."""

from datetime import UTC, datetime
from uuid import uuid4

from commandbus._core.process_sql import ProcessParams, ProcessParsers, ProcessSQL
from commandbus.models import ReplyOutcome
from commandbus.process.models import (
    ProcessAuditEntry,
    ProcessMetadata,
    ProcessStatus,
)


class TestProcessSQL:
    """Tests for ProcessSQL constants."""

    def test_select_columns_defined(self) -> None:
        """SELECT_COLUMNS should be defined."""
        assert ProcessSQL.SELECT_COLUMNS is not None
        assert "domain" in ProcessSQL.SELECT_COLUMNS
        assert "process_id" in ProcessSQL.SELECT_COLUMNS

    def test_save_defined(self) -> None:
        """SAVE SQL should be defined."""
        assert ProcessSQL.SAVE is not None
        assert "INSERT INTO" in ProcessSQL.SAVE
        assert "commandbus.process" in ProcessSQL.SAVE

    def test_update_defined(self) -> None:
        """UPDATE SQL should be defined."""
        assert ProcessSQL.UPDATE is not None
        assert "UPDATE" in ProcessSQL.UPDATE
        assert "NOW()" in ProcessSQL.UPDATE

    def test_get_by_id_defined(self) -> None:
        """GET_BY_ID SQL should be defined."""
        assert ProcessSQL.GET_BY_ID is not None
        assert "SELECT" in ProcessSQL.GET_BY_ID

    def test_find_by_status_defined(self) -> None:
        """FIND_BY_STATUS SQL should be defined."""
        assert ProcessSQL.FIND_BY_STATUS is not None
        assert "ANY" in ProcessSQL.FIND_BY_STATUS

    def test_log_step_defined(self) -> None:
        """LOG_STEP SQL should be defined."""
        assert ProcessSQL.LOG_STEP is not None
        assert "INSERT INTO" in ProcessSQL.LOG_STEP
        assert "process_audit" in ProcessSQL.LOG_STEP

    def test_update_step_reply_defined(self) -> None:
        """UPDATE_STEP_REPLY SQL should be defined."""
        assert ProcessSQL.UPDATE_STEP_REPLY is not None
        assert "UPDATE" in ProcessSQL.UPDATE_STEP_REPLY
        assert "reply_outcome" in ProcessSQL.UPDATE_STEP_REPLY

    def test_get_audit_trail_defined(self) -> None:
        """GET_AUDIT_TRAIL SQL should be defined."""
        assert ProcessSQL.GET_AUDIT_TRAIL is not None
        assert "ORDER BY sent_at" in ProcessSQL.GET_AUDIT_TRAIL

    def test_get_completed_steps_defined(self) -> None:
        """GET_COMPLETED_STEPS SQL should be defined."""
        assert ProcessSQL.GET_COMPLETED_STEPS is not None
        assert "SUCCESS" in ProcessSQL.GET_COMPLETED_STEPS


class TestProcessParams:
    """Tests for ProcessParams static methods."""

    def test_save_returns_tuple(self) -> None:
        """save should return tuple with correct length."""
        now = datetime.now(UTC)
        process = ProcessMetadata(
            domain="test",
            process_id=uuid4(),
            process_type="TestProcess",
            status=ProcessStatus.PENDING,
            current_step="step1",
            state={"key": "value"},
            created_at=now,
            updated_at=now,
        )
        params = ProcessParams.save(process, {"key": "value"})

        assert isinstance(params, tuple)
        assert len(params) == 12  # Includes batch_id
        assert params[0] == "test"
        assert params[3] == "PENDING"
        assert params[11] is None  # batch_id

    def test_update_returns_tuple(self) -> None:
        """update should return tuple with correct length."""
        now = datetime.now(UTC)
        process = ProcessMetadata(
            domain="test",
            process_id=uuid4(),
            process_type="TestProcess",
            status=ProcessStatus.IN_PROGRESS,
            current_step="step2",
            state={"key": "value"},
            created_at=now,
            updated_at=now,
        )
        params = ProcessParams.update(process, {"key": "value"})

        assert isinstance(params, tuple)
        assert len(params) == 8
        assert params[0] == "IN_PROGRESS"

    def test_get_by_id_returns_tuple(self) -> None:
        """get_by_id should return tuple."""
        process_id = uuid4()
        params = ProcessParams.get_by_id("test", process_id)

        assert params == ("test", process_id)

    def test_find_by_status_converts_enum_values(self) -> None:
        """find_by_status should convert status enums to values."""
        statuses = [ProcessStatus.PENDING, ProcessStatus.IN_PROGRESS]
        params = ProcessParams.find_by_status("test", statuses)

        assert params[0] == "test"
        assert params[1] == ["PENDING", "IN_PROGRESS"]

    def test_log_step_returns_tuple(self) -> None:
        """log_step should return tuple with correct length."""
        entry = ProcessAuditEntry(
            step_name="step1",
            command_id=uuid4(),
            command_type="TestCommand",
            command_data={"key": "value"},
            sent_at=datetime.now(UTC),
        )
        params = ProcessParams.log_step("test", uuid4(), entry)

        assert isinstance(params, tuple)
        assert len(params) == 10
        assert params[2] == "step1"

    def test_log_step_handles_none_data(self) -> None:
        """log_step should handle None command_data."""
        entry = ProcessAuditEntry(
            step_name="step1",
            command_id=uuid4(),
            command_type="TestCommand",
            command_data=None,
            sent_at=datetime.now(UTC),
        )
        params = ProcessParams.log_step("test", uuid4(), entry)

        assert params[5] is None

    def test_log_step_serializes_reply_outcome(self) -> None:
        """log_step should serialize reply_outcome to value."""
        entry = ProcessAuditEntry(
            step_name="step1",
            command_id=uuid4(),
            command_type="TestCommand",
            command_data=None,
            sent_at=datetime.now(UTC),
            reply_outcome=ReplyOutcome.SUCCESS,
        )
        params = ProcessParams.log_step("test", uuid4(), entry)

        assert params[7] == "SUCCESS"

    def test_update_step_reply_returns_tuple(self) -> None:
        """update_step_reply should return tuple with correct length."""
        entry = ProcessAuditEntry(
            step_name="step1",
            command_id=uuid4(),
            command_type="TestCommand",
            command_data=None,
            sent_at=datetime.now(UTC),
            reply_outcome=ReplyOutcome.SUCCESS,
            reply_data={"result": "ok"},
            received_at=datetime.now(UTC),
        )
        params = ProcessParams.update_step_reply("test", uuid4(), uuid4(), entry)

        assert isinstance(params, tuple)
        assert len(params) == 6
        assert params[0] == "SUCCESS"

    def test_get_audit_trail_returns_tuple(self) -> None:
        """get_audit_trail should return tuple."""
        process_id = uuid4()
        params = ProcessParams.get_audit_trail("test", process_id)

        assert params == ("test", process_id)

    def test_get_completed_steps_returns_tuple(self) -> None:
        """get_completed_steps should return tuple."""
        process_id = uuid4()
        params = ProcessParams.get_completed_steps("test", process_id)

        assert params == ("test", process_id)


class TestProcessParsers:
    """Tests for ProcessParsers static methods."""

    def test_from_row_parses_metadata(self) -> None:
        """from_row should parse database row to ProcessMetadata."""
        now = datetime.now(UTC)
        process_id = uuid4()
        row = (
            "test",
            process_id,
            "TestProcess",
            "PENDING",
            "step1",
            {"key": "value"},
            None,
            None,
            now,
            now,
            None,
        )

        result = ProcessParsers.from_row(row)

        assert isinstance(result, ProcessMetadata)
        assert result.domain == "test"
        assert result.process_id == process_id
        assert result.process_type == "TestProcess"
        assert result.status == ProcessStatus.PENDING
        assert result.current_step == "step1"
        assert result.state == {"key": "value"}

    def test_from_row_parses_json_string_state(self) -> None:
        """from_row should parse JSON string state."""
        now = datetime.now(UTC)
        row = (
            "test",
            uuid4(),
            "TestProcess",
            "IN_PROGRESS",
            "step2",
            '{"key": "value"}',  # JSON string
            None,
            None,
            now,
            now,
            None,
        )

        result = ProcessParsers.from_row(row)

        assert result.state == {"key": "value"}

    def test_from_rows_parses_list(self) -> None:
        """from_rows should parse list of rows."""
        now = datetime.now(UTC)
        rows = [
            ("test", uuid4(), "TestProcess", "PENDING", "step1", {}, None, None, now, now, None),
            (
                "test",
                uuid4(),
                "TestProcess",
                "IN_PROGRESS",
                "step2",
                {},
                None,
                None,
                now,
                now,
                None,
            ),
        ]

        result = ProcessParsers.from_rows(rows)

        assert len(result) == 2
        assert all(isinstance(p, ProcessMetadata) for p in result)

    def test_audit_entry_from_row_parses_entry(self) -> None:
        """audit_entry_from_row should parse database row to ProcessAuditEntry."""
        now = datetime.now(UTC)
        command_id = uuid4()
        row = (
            "step1",
            command_id,
            "TestCommand",
            {"key": "value"},
            now,
            "SUCCESS",
            {"result": "ok"},
            now,
        )

        result = ProcessParsers.audit_entry_from_row(row)

        assert isinstance(result, ProcessAuditEntry)
        assert result.step_name == "step1"
        assert result.command_id == command_id
        assert result.command_type == "TestCommand"
        assert result.command_data == {"key": "value"}
        assert result.reply_outcome == ReplyOutcome.SUCCESS
        assert result.reply_data == {"result": "ok"}

    def test_audit_entry_from_row_handles_none_outcome(self) -> None:
        """audit_entry_from_row should handle None reply_outcome."""
        now = datetime.now(UTC)
        row = (
            "step1",
            uuid4(),
            "TestCommand",
            None,
            now,
            None,  # No reply yet
            None,
            None,
        )

        result = ProcessParsers.audit_entry_from_row(row)

        assert result.reply_outcome is None

    def test_audit_entry_from_row_parses_json_strings(self) -> None:
        """audit_entry_from_row should parse JSON string data."""
        now = datetime.now(UTC)
        row = (
            "step1",
            uuid4(),
            "TestCommand",
            '{"key": "value"}',  # JSON string
            now,
            "SUCCESS",
            '{"result": "ok"}',  # JSON string
            now,
        )

        result = ProcessParsers.audit_entry_from_row(row)

        assert result.command_data == {"key": "value"}
        assert result.reply_data == {"result": "ok"}

    def test_audit_entries_from_rows_parses_list(self) -> None:
        """audit_entries_from_rows should parse list of rows."""
        now = datetime.now(UTC)
        rows = [
            ("step1", uuid4(), "TestCommand", None, now, None, None, None),
            ("step2", uuid4(), "TestCommand", None, now, "SUCCESS", None, now),
        ]

        result = ProcessParsers.audit_entries_from_rows(rows)

        assert len(result) == 2
        assert all(isinstance(e, ProcessAuditEntry) for e in result)
