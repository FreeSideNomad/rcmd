"""Unit tests for commandbus._core.pgmq_sql module."""

import json
from datetime import datetime

from commandbus._core.pgmq_sql import (
    PGMQ_NOTIFY_CHANNEL,
    PgmqMessage,
    PgmqParams,
    PgmqParsers,
    PgmqSQL,
)


class TestPgmqMessage:
    """Tests for PgmqMessage dataclass."""

    def test_pgmq_message_creation(self) -> None:
        """PgmqMessage should store all fields correctly."""
        msg = PgmqMessage(
            msg_id=123,
            read_count=1,
            enqueued_at="2024-01-01T12:00:00",
            vt="2024-01-01T12:00:30",
            message={"command_id": "abc", "data": {"key": "value"}},
        )

        assert msg.msg_id == 123
        assert msg.read_count == 1
        assert msg.enqueued_at == "2024-01-01T12:00:00"
        assert msg.vt == "2024-01-01T12:00:30"
        assert msg.message == {"command_id": "abc", "data": {"key": "value"}}


class TestPgmqSQL:
    """Tests for PgmqSQL class."""

    def test_create_queue_has_placeholder(self) -> None:
        """CREATE_QUEUE SQL should have 1 placeholder."""
        assert PgmqSQL.CREATE_QUEUE.count("%s") == 1

    def test_send_has_placeholders(self) -> None:
        """SEND SQL should have 3 placeholders."""
        assert PgmqSQL.SEND.count("%s") == 3

    def test_send_batch_has_placeholders(self) -> None:
        """SEND_BATCH SQL should have 3 placeholders."""
        assert PgmqSQL.SEND_BATCH.count("%s") == 3

    def test_read_has_placeholders(self) -> None:
        """READ SQL should have 3 placeholders."""
        assert PgmqSQL.READ.count("%s") == 3

    def test_delete_has_placeholders(self) -> None:
        """DELETE SQL should have 2 placeholders."""
        assert PgmqSQL.DELETE.count("%s") == 2

    def test_archive_has_placeholders(self) -> None:
        """ARCHIVE SQL should have 2 placeholders."""
        assert PgmqSQL.ARCHIVE.count("%s") == 2

    def test_set_vt_has_placeholders(self) -> None:
        """SET_VT SQL should have 3 placeholders."""
        assert PgmqSQL.SET_VT.count("%s") == 3

    def test_notify_channel_returns_formatted_name(self) -> None:
        """notify_channel() should return correctly formatted channel name."""
        channel = PgmqSQL.notify_channel("test__commands")
        assert channel == "pgmq_notify_test__commands"

    def test_notify_channel_uses_constant(self) -> None:
        """notify_channel() should use PGMQ_NOTIFY_CHANNEL constant."""
        channel = PgmqSQL.notify_channel("myqueue")
        assert channel.startswith(PGMQ_NOTIFY_CHANNEL)

    def test_notify_sql_returns_sql_statement(self) -> None:
        """notify_sql() should return NOTIFY SQL statement."""
        sql = PgmqSQL.notify_sql("test__commands")
        assert sql == "NOTIFY pgmq_notify_test__commands"

    def test_notify_sql_with_different_queue(self) -> None:
        """notify_sql() should work with various queue names."""
        sql = PgmqSQL.notify_sql("payments__commands")
        assert sql == "NOTIFY pgmq_notify_payments__commands"


class TestPgmqParams:
    """Tests for PgmqParams class."""

    def test_create_queue_returns_tuple(self) -> None:
        """create_queue() should return 1-element tuple."""
        params = PgmqParams.create_queue("test__commands")
        assert params == ("test__commands",)

    def test_send_returns_tuple_with_json(self) -> None:
        """send() should return tuple with JSON-serialized message."""
        message = {"command_id": "abc", "data": {"key": "value"}}
        params = PgmqParams.send("test__commands", message, delay=5)

        assert params[0] == "test__commands"
        assert params[1] == json.dumps(message)
        assert params[2] == 5

    def test_send_default_delay(self) -> None:
        """send() should default delay to 0."""
        params = PgmqParams.send("test__commands", {"key": "value"})
        assert params[2] == 0

    def test_send_batch_returns_tuple_with_json_list(self) -> None:
        """send_batch() should return tuple with JSON-serialized messages list."""
        messages = [{"id": 1}, {"id": 2}, {"id": 3}]
        params = PgmqParams.send_batch("test__commands", messages, delay=10)

        assert params[0] == "test__commands"
        assert params[1] == [json.dumps(m) for m in messages]
        assert params[2] == 10

    def test_send_batch_empty_list(self) -> None:
        """send_batch() should handle empty message list."""
        params = PgmqParams.send_batch("test__commands", [])
        assert params[1] == []

    def test_read_returns_tuple(self) -> None:
        """read() should return 3-element tuple."""
        params = PgmqParams.read("test__commands", visibility_timeout=60, batch_size=10)

        assert params == ("test__commands", 60, 10)

    def test_read_default_values(self) -> None:
        """read() should use default values."""
        params = PgmqParams.read("test__commands")
        assert params == ("test__commands", 30, 1)

    def test_delete_returns_tuple(self) -> None:
        """delete() should return 2-element tuple."""
        params = PgmqParams.delete("test__commands", 123)
        assert params == ("test__commands", 123)

    def test_archive_returns_tuple(self) -> None:
        """archive() should return 2-element tuple."""
        params = PgmqParams.archive("test__commands", 456)
        assert params == ("test__commands", 456)

    def test_set_vt_returns_tuple(self) -> None:
        """set_vt() should return 3-element tuple."""
        params = PgmqParams.set_vt("test__commands", 789, 90)
        assert params == ("test__commands", 789, 90)


class TestPgmqParsers:
    """Tests for PgmqParsers class."""

    def test_from_row_creates_message(self) -> None:
        """from_row() should create PgmqMessage from tuple."""
        row = (
            123,  # msg_id
            1,  # read_ct
            "2024-01-01T12:00:00+00:00",  # enqueued_at
            "2024-01-01T12:00:30+00:00",  # vt
            {"command_id": "abc", "data": {"key": "value"}},  # message (dict)
        )

        msg = PgmqParsers.from_row(row)

        assert msg.msg_id == 123
        assert msg.read_count == 1
        assert msg.enqueued_at == "2024-01-01T12:00:00+00:00"
        assert msg.vt == "2024-01-01T12:00:30+00:00"
        assert msg.message == {"command_id": "abc", "data": {"key": "value"}}

    def test_from_row_parses_json_string_message(self) -> None:
        """from_row() should parse JSON string message."""
        row = (
            456,
            2,
            "2024-01-01T12:00:00",
            "2024-01-01T12:00:30",
            '{"command_id": "xyz", "data": {"nested": true}}',  # JSON string
        )

        msg = PgmqParsers.from_row(row)

        assert msg.message == {"command_id": "xyz", "data": {"nested": True}}

    def test_from_row_converts_timestamps_to_string(self) -> None:
        """from_row() should convert timestamps to strings."""
        row = (
            789,
            0,
            datetime(2024, 1, 1, 12, 0, 0),  # datetime object
            datetime(2024, 1, 1, 12, 0, 30),  # datetime object
            {"key": "value"},
        )

        msg = PgmqParsers.from_row(row)

        assert isinstance(msg.enqueued_at, str)
        assert isinstance(msg.vt, str)

    def test_from_rows_creates_list(self) -> None:
        """from_rows() should create list of PgmqMessage."""
        rows = [
            (1, 0, "2024-01-01T12:00:00", "2024-01-01T12:00:30", {"id": 1}),
            (2, 1, "2024-01-01T12:01:00", "2024-01-01T12:01:30", {"id": 2}),
            (3, 0, "2024-01-01T12:02:00", "2024-01-01T12:02:30", {"id": 3}),
        ]

        messages = PgmqParsers.from_rows(rows)

        assert len(messages) == 3
        assert messages[0].msg_id == 1
        assert messages[1].msg_id == 2
        assert messages[2].msg_id == 3

    def test_from_rows_handles_empty_list(self) -> None:
        """from_rows() should handle empty list."""
        messages = PgmqParsers.from_rows([])
        assert messages == []

    def test_from_rows_with_mixed_message_formats(self) -> None:
        """from_rows() should handle both dict and string messages."""
        rows = [
            (1, 0, "2024-01-01T12:00:00", "2024-01-01T12:00:30", {"id": 1}),
            (2, 1, "2024-01-01T12:01:00", "2024-01-01T12:01:30", '{"id": 2}'),
        ]

        messages = PgmqParsers.from_rows(rows)

        assert messages[0].message == {"id": 1}
        assert messages[1].message == {"id": 2}


class TestPgmqNotifyChannel:
    """Tests for PGMQ_NOTIFY_CHANNEL constant."""

    def test_notify_channel_constant_value(self) -> None:
        """PGMQ_NOTIFY_CHANNEL should have expected value."""
        assert PGMQ_NOTIFY_CHANNEL == "pgmq_notify"
