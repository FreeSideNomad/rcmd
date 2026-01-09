"""Unit tests for commandbus._core.command_sql module."""

from datetime import datetime
from uuid import uuid4

import pytest

from commandbus._core.command_sql import CommandParams, CommandParsers, CommandSQL
from commandbus.models import CommandMetadata, CommandStatus


class TestCommandSQL:
    """Tests for CommandSQL class."""

    def test_select_columns_defined(self) -> None:
        """SELECT_COLUMNS should contain expected column list."""
        assert "domain" in CommandSQL.SELECT_COLUMNS
        assert "command_id" in CommandSQL.SELECT_COLUMNS
        assert "command_type" in CommandSQL.SELECT_COLUMNS
        assert "status" in CommandSQL.SELECT_COLUMNS
        assert "batch_id" in CommandSQL.SELECT_COLUMNS

    def test_save_sql_has_correct_placeholders(self) -> None:
        """SAVE SQL should have 13 placeholders."""
        assert CommandSQL.SAVE.count("%s") == 13

    def test_get_sql_has_placeholders(self) -> None:
        """GET SQL should have 2 placeholders for domain and command_id."""
        assert CommandSQL.GET.count("%s") == 2

    def test_update_status_sql_has_placeholders(self) -> None:
        """UPDATE_STATUS SQL should have 3 placeholders."""
        assert CommandSQL.UPDATE_STATUS.count("%s") == 3

    def test_receive_command_sql_has_placeholders(self) -> None:
        """RECEIVE_COMMAND SQL should have 3 placeholders."""
        assert CommandSQL.RECEIVE_COMMAND.count("%s") == 3

    def test_finish_command_sql_has_placeholders(self) -> None:
        """FINISH_COMMAND SQL should have 6 placeholders."""
        assert CommandSQL.FINISH_COMMAND.count("%s") == 6

    def test_exists_sql_has_placeholders(self) -> None:
        """EXISTS SQL should have 2 placeholders."""
        assert CommandSQL.EXISTS.count("%s") == 2

    def test_sp_receive_command_has_placeholders(self) -> None:
        """SP_RECEIVE_COMMAND SQL should have 5 placeholders."""
        assert CommandSQL.SP_RECEIVE_COMMAND.count("%s") == 5

    def test_sp_finish_command_has_placeholders(self) -> None:
        """SP_FINISH_COMMAND SQL should have 9 placeholders."""
        assert CommandSQL.SP_FINISH_COMMAND.count("%s") == 9

    def test_sp_fail_command_has_placeholders(self) -> None:
        """SP_FAIL_COMMAND SQL should have 8 placeholders."""
        assert CommandSQL.SP_FAIL_COMMAND.count("%s") == 8


class TestCommandParams:
    """Tests for CommandParams class."""

    @pytest.fixture
    def sample_metadata(self) -> CommandMetadata:
        """Create sample CommandMetadata for testing."""
        return CommandMetadata(
            domain="test",
            command_id=uuid4(),
            command_type="TestCommand",
            status=CommandStatus.PENDING,
            attempts=0,
            max_attempts=3,
            msg_id=123,
            correlation_id=uuid4(),
            reply_to="reply_queue",
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            updated_at=datetime(2024, 1, 1, 12, 0, 0),
            batch_id=uuid4(),
        )

    def test_save_returns_correct_tuple_length(self, sample_metadata: CommandMetadata) -> None:
        """save() should return 13 parameters."""
        params = CommandParams.save(sample_metadata, "test__commands")
        assert len(params) == 13

    def test_save_returns_correct_values(self, sample_metadata: CommandMetadata) -> None:
        """save() should return values in correct order."""
        params = CommandParams.save(sample_metadata, "test__commands")

        assert params[0] == sample_metadata.domain
        assert params[1] == "test__commands"
        assert params[2] == sample_metadata.msg_id
        assert params[3] == sample_metadata.command_id
        assert params[4] == sample_metadata.command_type
        assert params[5] == sample_metadata.status.value
        assert params[6] == sample_metadata.attempts
        assert params[7] == sample_metadata.max_attempts
        assert params[8] == sample_metadata.correlation_id
        assert params[9] == sample_metadata.reply_to
        assert params[10] == sample_metadata.created_at
        assert params[11] == sample_metadata.updated_at
        assert params[12] == sample_metadata.batch_id

    def test_save_handles_none_reply_to(self, sample_metadata: CommandMetadata) -> None:
        """save() should convert None reply_to to empty string."""
        sample_metadata.reply_to = None
        params = CommandParams.save(sample_metadata, "test__commands")
        assert params[9] == ""

    def test_update_status_returns_correct_tuple(self) -> None:
        """update_status() should return 3 parameters."""
        command_id = uuid4()
        params = CommandParams.update_status(CommandStatus.COMPLETED, "test", command_id)

        assert params == ("COMPLETED", "test", command_id)

    def test_update_msg_id_returns_correct_tuple(self) -> None:
        """update_msg_id() should return 3 parameters."""
        command_id = uuid4()
        params = CommandParams.update_msg_id(456, "test", command_id)

        assert params == (456, "test", command_id)

    def test_receive_command_returns_correct_tuple(self) -> None:
        """receive_command() should return 3 parameters."""
        command_id = uuid4()
        params = CommandParams.receive_command(CommandStatus.IN_PROGRESS, "test", command_id)

        assert params == ("IN_PROGRESS", "test", command_id)

    def test_update_error_returns_correct_tuple(self) -> None:
        """update_error() should return 5 parameters."""
        command_id = uuid4()
        params = CommandParams.update_error(
            "TRANSIENT", "TIMEOUT", "Connection timed out", "test", command_id
        )

        assert params == ("TRANSIENT", "TIMEOUT", "Connection timed out", "test", command_id)

    def test_finish_command_returns_correct_tuple(self) -> None:
        """finish_command() should return 6 parameters."""
        command_id = uuid4()
        params = CommandParams.finish_command(
            CommandStatus.COMPLETED, None, None, None, "test", command_id
        )

        assert params == ("COMPLETED", None, None, None, "test", command_id)

    def test_finish_command_with_error(self) -> None:
        """finish_command() should include error information."""
        command_id = uuid4()
        params = CommandParams.finish_command(
            CommandStatus.FAILED, "PERMANENT", "INVALID_DATA", "Bad input", "test", command_id
        )

        assert params[0] == "FAILED"
        assert params[1] == "PERMANENT"
        assert params[2] == "INVALID_DATA"
        assert params[3] == "Bad input"

    def test_sp_receive_command_returns_correct_tuple(self) -> None:
        """sp_receive_command() should return 5 parameters."""
        command_id = uuid4()
        params = CommandParams.sp_receive_command("test", command_id, "IN_PROGRESS", 123, 5)

        assert params == ("test", command_id, "IN_PROGRESS", 123, 5)

    def test_sp_receive_command_with_defaults(self) -> None:
        """sp_receive_command() should use default values."""
        command_id = uuid4()
        params = CommandParams.sp_receive_command("test", command_id)

        assert params == ("test", command_id, "IN_PROGRESS", None, None)

    def test_sp_finish_command_returns_correct_tuple(self) -> None:
        """sp_finish_command() should return 9 parameters."""
        command_id = uuid4()
        batch_id = uuid4()
        params = CommandParams.sp_finish_command(
            "test",
            command_id,
            CommandStatus.COMPLETED,
            "COMPLETED",
            None,
            None,
            None,
            '{"key": "value"}',
            batch_id,
        )

        assert len(params) == 9
        assert params[0] == "test"
        assert params[1] == command_id
        assert params[2] == "COMPLETED"
        assert params[3] == "COMPLETED"
        assert params[7] == '{"key": "value"}'
        assert params[8] == batch_id

    def test_sp_fail_command_returns_correct_tuple(self) -> None:
        """sp_fail_command() should return 8 parameters."""
        command_id = uuid4()
        params = CommandParams.sp_fail_command(
            "test", command_id, "TRANSIENT", "TIMEOUT", "Timed out", 2, 3, 456
        )

        assert len(params) == 8
        assert params[0] == "test"
        assert params[1] == command_id
        assert params[2] == "TRANSIENT"
        assert params[3] == "TIMEOUT"
        assert params[4] == "Timed out"
        assert params[5] == 2
        assert params[6] == 3
        assert params[7] == 456


class TestCommandParsers:
    """Tests for CommandParsers class."""

    def test_from_row_creates_metadata(self) -> None:
        """from_row() should create CommandMetadata from tuple."""
        command_id = uuid4()
        correlation_id = uuid4()
        batch_id = uuid4()
        created_at = datetime(2024, 1, 1, 12, 0, 0)
        updated_at = datetime(2024, 1, 1, 12, 1, 0)

        row = (
            "test",  # domain
            command_id,  # command_id
            "TestCommand",  # command_type
            "PENDING",  # status
            0,  # attempts
            3,  # max_attempts
            123,  # msg_id
            correlation_id,  # correlation_id
            "reply_queue",  # reply_queue
            None,  # last_error_type
            None,  # last_error_code
            None,  # last_error_msg
            created_at,  # created_at
            updated_at,  # updated_at
            batch_id,  # batch_id
        )

        metadata = CommandParsers.from_row(row)

        assert metadata.domain == "test"
        assert metadata.command_id == command_id
        assert metadata.command_type == "TestCommand"
        assert metadata.status == CommandStatus.PENDING
        assert metadata.attempts == 0
        assert metadata.max_attempts == 3
        assert metadata.msg_id == 123
        assert metadata.correlation_id == correlation_id
        assert metadata.reply_to == "reply_queue"
        assert metadata.last_error_type is None
        assert metadata.last_error_code is None
        assert metadata.last_error_msg is None
        assert metadata.created_at == created_at
        assert metadata.updated_at == updated_at
        assert metadata.batch_id == batch_id

    def test_from_row_handles_empty_reply_to(self) -> None:
        """from_row() should convert empty string reply_to to None."""
        row = (
            "test",
            uuid4(),
            "TestCommand",
            "PENDING",
            0,
            3,
            123,
            None,
            "",  # empty reply_queue
            None,
            None,
            None,
            datetime.now(),
            datetime.now(),
            None,
        )

        metadata = CommandParsers.from_row(row)
        assert metadata.reply_to is None

    def test_from_row_preserves_error_info(self) -> None:
        """from_row() should preserve error information."""
        row = (
            "test",
            uuid4(),
            "TestCommand",
            "FAILED",
            3,
            3,
            123,
            None,
            None,
            "TRANSIENT",  # last_error_type
            "TIMEOUT",  # last_error_code
            "Connection timed out",  # last_error_msg
            datetime.now(),
            datetime.now(),
            None,
        )

        metadata = CommandParsers.from_row(row)

        assert metadata.last_error_type == "TRANSIENT"
        assert metadata.last_error_code == "TIMEOUT"
        assert metadata.last_error_msg == "Connection timed out"

    def test_from_row_handles_all_statuses(self) -> None:
        """from_row() should handle all CommandStatus values."""
        for status in CommandStatus:
            row = (
                "test",
                uuid4(),
                "TestCommand",
                status.value,
                0,
                3,
                None,
                None,
                None,
                None,
                None,
                None,
                datetime.now(),
                datetime.now(),
                None,
            )

            metadata = CommandParsers.from_row(row)
            assert metadata.status == status

    def test_from_rows_creates_list(self) -> None:
        """from_rows() should create list of CommandMetadata."""
        rows = [
            (
                "test",
                uuid4(),
                "TestCommand1",
                "PENDING",
                0,
                3,
                1,
                None,
                None,
                None,
                None,
                None,
                datetime.now(),
                datetime.now(),
                None,
            ),
            (
                "test",
                uuid4(),
                "TestCommand2",
                "COMPLETED",
                1,
                3,
                2,
                None,
                None,
                None,
                None,
                None,
                datetime.now(),
                datetime.now(),
                None,
            ),
        ]

        metadata_list = CommandParsers.from_rows(rows)

        assert len(metadata_list) == 2
        assert metadata_list[0].command_type == "TestCommand1"
        assert metadata_list[1].command_type == "TestCommand2"

    def test_from_rows_handles_empty_list(self) -> None:
        """from_rows() should handle empty list."""
        metadata_list = CommandParsers.from_rows([])
        assert metadata_list == []
