"""Unit tests for commandbus.sync.pgmq module."""

from unittest.mock import MagicMock, patch

import pytest

from commandbus._core.pgmq_sql import PgmqMessage, PgmqSQL
from commandbus.sync.pgmq import SyncPgmqClient


class TestSyncPgmqClientInit:
    """Tests for SyncPgmqClient initialization."""

    def test_init_stores_pool(self) -> None:
        """SyncPgmqClient should store the pool reference."""
        pool = MagicMock()
        client = SyncPgmqClient(pool)
        assert client._pool is pool


class TestSyncPgmqClientCreateQueue:
    """Tests for SyncPgmqClient.create_queue method."""

    def test_create_queue_with_pool(self) -> None:
        """create_queue should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.create_queue("test_queue")

        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert args[0][0] == PgmqSQL.CREATE_QUEUE
        assert args[0][1] == ("test_queue",)

    def test_create_queue_with_provided_connection(self) -> None:
        """create_queue should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        client = SyncPgmqClient(pool)
        client.create_queue("test_queue", conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()


class TestSyncPgmqClientSend:
    """Tests for SyncPgmqClient.send method."""

    def test_send_returns_msg_id(self) -> None:
        """send should return message ID."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (123,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        msg_id = client.send("test_queue", {"key": "value"})

        assert msg_id == 123

    def test_send_executes_correct_sql(self) -> None:
        """send should execute SEND SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (456,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.send("test_queue", {"key": "value"}, delay=5)

        # Verify SQL was executed
        assert cursor.execute.call_count == 2  # SEND + NOTIFY
        first_call = cursor.execute.call_args_list[0]
        assert first_call[0][0] == PgmqSQL.SEND

    def test_send_with_delay(self) -> None:
        """send should pass delay to PGMQ."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (789,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.send("test_queue", {"key": "value"}, delay=10)

        first_call = cursor.execute.call_args_list[0]
        params = first_call[0][1]
        assert params[2] == 10  # delay is third param

    def test_send_with_provided_connection(self) -> None:
        """send should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (111,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        client = SyncPgmqClient(pool)
        msg_id = client.send("test_queue", {"key": "value"}, conn=conn)

        assert msg_id == 111
        pool.connection.assert_not_called()

    def test_send_raises_on_failure(self) -> None:
        """send should raise RuntimeError when PGMQ returns None."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)

        with pytest.raises(RuntimeError, match="Failed to send message"):
            client.send("test_queue", {"key": "value"})

    def test_send_sends_notify(self) -> None:
        """send should send NOTIFY after enqueuing."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (123,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.send("test_queue", {"key": "value"})

        # Second call should be NOTIFY
        second_call = cursor.execute.call_args_list[1]
        assert "NOTIFY" in second_call[0][0]
        assert "test_queue" in second_call[0][0]


class TestSyncPgmqClientSendBatch:
    """Tests for SyncPgmqClient.send_batch method."""

    def test_send_batch_returns_msg_ids(self) -> None:
        """send_batch should return list of message IDs."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [(1,), (2,), (3,)]
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        msg_ids = client.send_batch("test_queue", [{"id": 1}, {"id": 2}, {"id": 3}])

        assert msg_ids == [1, 2, 3]

    def test_send_batch_empty_list(self) -> None:
        """send_batch should return empty list for empty input."""
        pool = MagicMock()
        client = SyncPgmqClient(pool)

        msg_ids = client.send_batch("test_queue", [])

        assert msg_ids == []
        pool.connection.assert_not_called()

    def test_send_batch_executes_batch_sql(self) -> None:
        """send_batch should use SEND_BATCH SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [(1,)]
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.send_batch("test_queue", [{"id": 1}])

        first_call = cursor.execute.call_args
        assert first_call[0][0] == PgmqSQL.SEND_BATCH


class TestSyncPgmqClientNotify:
    """Tests for SyncPgmqClient.notify method."""

    def test_notify_sends_notification(self) -> None:
        """notify should send NOTIFY SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.notify("test_queue")

        cursor.execute.assert_called_once()
        sql = cursor.execute.call_args[0][0]
        assert "NOTIFY" in sql
        assert "test_queue" in sql

    def test_notify_with_provided_connection(self) -> None:
        """notify should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        client = SyncPgmqClient(pool)
        client.notify("test_queue", conn=conn)

        cursor.execute.assert_called_once()
        pool.connection.assert_not_called()


class TestSyncPgmqClientRead:
    """Tests for SyncPgmqClient.read method."""

    def test_read_returns_messages(self) -> None:
        """read should return list of PgmqMessage."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (1, 0, "2024-01-01T12:00:00", "2024-01-01T12:00:30", {"id": 1}),
            (2, 1, "2024-01-01T12:01:00", "2024-01-01T12:01:30", {"id": 2}),
        ]
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        messages = client.read("test_queue", visibility_timeout=60, batch_size=10)

        assert len(messages) == 2
        assert isinstance(messages[0], PgmqMessage)
        assert messages[0].msg_id == 1
        assert messages[1].msg_id == 2

    def test_read_empty_queue(self) -> None:
        """read should return empty list when queue is empty."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        messages = client.read("test_queue")

        assert messages == []

    def test_read_executes_correct_sql(self) -> None:
        """read should execute READ SQL with correct parameters."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.read("test_queue", visibility_timeout=45, batch_size=5)

        call_args = cursor.execute.call_args
        assert call_args[0][0] == PgmqSQL.READ
        assert call_args[0][1] == ("test_queue", 45, 5)

    def test_read_default_parameters(self) -> None:
        """read should use default parameters."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.read("test_queue")

        call_args = cursor.execute.call_args
        assert call_args[0][1] == ("test_queue", 30, 1)


class TestSyncPgmqClientReadWithPoll:
    """Tests for SyncPgmqClient.read_with_poll method."""

    def test_read_with_poll_returns_immediately_when_messages_available(self) -> None:
        """read_with_poll should return immediately when messages found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            (1, 0, "2024-01-01T12:00:00", "2024-01-01T12:00:30", {"id": 1}),
        ]
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        messages = client.read_with_poll("test_queue", max_wait=10)

        assert len(messages) == 1
        assert messages[0].msg_id == 1

    @patch("commandbus.sync.pgmq.time.sleep")
    @patch("commandbus.sync.pgmq.time.monotonic")
    def test_read_with_poll_polls_until_messages(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """read_with_poll should poll until messages available."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        # First two reads return empty, third returns message
        cursor.fetchall.side_effect = [[], [], [(1, 0, "ts", "vt", {"id": 1})]]
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        # Simulate time progression
        mock_monotonic.side_effect = [0, 1, 2, 3]

        client = SyncPgmqClient(pool)
        messages = client.read_with_poll("test_queue", poll_interval=1.0, max_wait=60)

        assert len(messages) == 1
        assert mock_sleep.call_count == 2  # Slept twice before finding message

    @patch("commandbus.sync.pgmq.time.sleep")
    @patch("commandbus.sync.pgmq.time.monotonic")
    def test_read_with_poll_respects_max_wait(
        self, mock_monotonic: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """read_with_poll should stop after max_wait exceeded."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []  # Always empty
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        # Simulate time: 0, 2, 4, 6 (exceeds max_wait of 5)
        mock_monotonic.side_effect = [0, 2, 4, 6]

        client = SyncPgmqClient(pool)
        messages = client.read_with_poll("test_queue", poll_interval=2.0, max_wait=5)

        assert messages == []


class TestSyncPgmqClientDelete:
    """Tests for SyncPgmqClient.delete method."""

    def test_delete_returns_true_on_success(self) -> None:
        """delete should return True when message deleted."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        result = client.delete("test_queue", 123)

        assert result is True

    def test_delete_returns_false_when_not_found(self) -> None:
        """delete should return False when message not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        result = client.delete("test_queue", 999)

        assert result is False

    def test_delete_executes_correct_sql(self) -> None:
        """delete should execute DELETE SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.delete("test_queue", 456)

        call_args = cursor.execute.call_args
        assert call_args[0][0] == PgmqSQL.DELETE
        assert call_args[0][1] == ("test_queue", 456)


class TestSyncPgmqClientArchive:
    """Tests for SyncPgmqClient.archive method."""

    def test_archive_returns_true_on_success(self) -> None:
        """archive should return True when message archived."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        result = client.archive("test_queue", 123)

        assert result is True

    def test_archive_executes_correct_sql(self) -> None:
        """archive should execute ARCHIVE SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.archive("test_queue", 789)

        call_args = cursor.execute.call_args
        assert call_args[0][0] == PgmqSQL.ARCHIVE
        assert call_args[0][1] == ("test_queue", 789)


class TestSyncPgmqClientSetVt:
    """Tests for SyncPgmqClient.set_vt method."""

    def test_set_vt_returns_true_on_success(self) -> None:
        """set_vt should return True when timeout set."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (1, 0, "ts", "vt", {})
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        result = client.set_vt("test_queue", 123, 60)

        assert result is True

    def test_set_vt_returns_false_when_not_found(self) -> None:
        """set_vt should return False when message not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        result = client.set_vt("test_queue", 999, 60)

        assert result is False

    def test_set_vt_executes_correct_sql(self) -> None:
        """set_vt should execute SET_VT SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (1, 0, "ts", "vt", {})
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        client = SyncPgmqClient(pool)
        client.set_vt("test_queue", 456, 90)

        call_args = cursor.execute.call_args
        assert call_args[0][0] == PgmqSQL.SET_VT
        assert call_args[0][1] == ("test_queue", 456, 90)


class TestSyncPgmqClientTransactionSupport:
    """Tests for transaction support across all methods."""

    def test_all_methods_support_provided_connection(self) -> None:
        """All methods should accept and use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (123,)
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        client = SyncPgmqClient(pool)

        # All methods with conn parameter
        client.create_queue("q", conn=conn)
        client.send("q", {}, conn=conn)
        client.send_batch("q", [{}], conn=conn)
        client.notify("q", conn=conn)
        client.read("q", conn=conn)
        client.delete("q", 1, conn=conn)
        client.archive("q", 1, conn=conn)
        client.set_vt("q", 1, 30, conn=conn)

        # Pool should never be accessed
        pool.connection.assert_not_called()
