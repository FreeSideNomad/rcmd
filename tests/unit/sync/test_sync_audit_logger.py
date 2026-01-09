"""Unit tests for commandbus.sync.repositories.audit module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from commandbus.models import AuditEvent
from commandbus.repositories.audit import AuditEventType
from commandbus.sync.repositories.audit import SyncAuditLogger


class TestSyncAuditLoggerInit:
    """Tests for SyncAuditLogger initialization."""

    def test_init_stores_pool(self) -> None:
        """SyncAuditLogger should store the pool reference."""
        pool = MagicMock()
        logger = SyncAuditLogger(pool)
        assert logger._pool is pool


class TestSyncAuditLoggerLog:
    """Tests for SyncAuditLogger.log method."""

    def test_log_with_pool(self) -> None:
        """log should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        logger = SyncAuditLogger(pool)
        command_id = uuid4()
        logger.log("test", command_id, AuditEventType.SENT)

        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert "INSERT INTO commandbus.audit" in args[0][0]

    def test_log_with_provided_connection(self) -> None:
        """log should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        logger = SyncAuditLogger(pool)
        command_id = uuid4()
        logger.log("test", command_id, AuditEventType.COMPLETED, conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_log_passes_correct_params(self) -> None:
        """log should pass correct parameters to execute."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        logger = SyncAuditLogger(pool)
        command_id = uuid4()
        logger.log("test", command_id, AuditEventType.SENT)

        args = conn.execute.call_args
        params = args[0][1]
        assert params[0] == "test"  # domain
        assert params[1] == command_id  # command_id
        assert params[2] == "SENT"  # event_type
        assert params[3] is None  # details_json (no details)

    def test_log_serializes_details(self) -> None:
        """log should serialize details to JSON."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        logger = SyncAuditLogger(pool)
        command_id = uuid4()
        details = {"error_code": "ERR001", "message": "Test error"}
        logger.log("test", command_id, AuditEventType.FAILED, details=details)

        args = conn.execute.call_args
        params = args[0][1]
        assert '"error_code"' in params[3]  # JSON string contains key
        assert '"ERR001"' in params[3]

    def test_log_all_event_types(self) -> None:
        """log should work with all AuditEventType values."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        logger = SyncAuditLogger(pool)
        command_id = uuid4()

        for event_type in AuditEventType:
            conn.reset_mock()
            logger.log("test", command_id, event_type)

            args = conn.execute.call_args
            params = args[0][1]
            assert params[2] == event_type.value


class TestSyncAuditLoggerLogBatch:
    """Tests for SyncAuditLogger.log_batch method."""

    def test_log_batch_empty_list(self) -> None:
        """log_batch should do nothing for empty list."""
        pool = MagicMock()
        conn = MagicMock()

        logger = SyncAuditLogger(pool)
        logger.log_batch([], conn)

        conn.cursor.assert_not_called()

    def test_log_batch_executes_many(self) -> None:
        """log_batch should execute many for multiple events."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        logger = SyncAuditLogger(pool)
        events = [
            ("test", uuid4(), AuditEventType.SENT, None),
            ("test", uuid4(), AuditEventType.COMPLETED, {"result": "ok"}),
        ]
        logger.log_batch(events, conn)

        cursor.executemany.assert_called_once()
        args = cursor.executemany.call_args
        assert "INSERT INTO commandbus.audit" in args[0][0]
        assert len(args[0][1]) == 2

    def test_log_batch_serializes_details(self) -> None:
        """log_batch should serialize details to JSON."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        logger = SyncAuditLogger(pool)
        events = [
            ("test", uuid4(), AuditEventType.FAILED, {"error": "test"}),
        ]
        logger.log_batch(events, conn)

        args = cursor.executemany.call_args
        params = args[0][1]
        assert '"error"' in params[0][3]  # JSON serialized


class TestSyncAuditLoggerGetEvents:
    """Tests for SyncAuditLogger.get_events method."""

    def test_get_events_returns_list(self) -> None:
        """get_events should return list of AuditEvent."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        now = datetime.now(UTC)
        command_id = uuid4()
        rows = [
            (1, "test", command_id, "SENT", now, None),
            (2, "test", command_id, "COMPLETED", now, {"result": "ok"}),
        ]
        cursor.fetchall.return_value = rows
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        logger = SyncAuditLogger(pool)
        events = logger.get_events(command_id)

        assert len(events) == 2
        assert all(isinstance(e, AuditEvent) for e in events)
        assert events[0].audit_id == 1
        assert events[0].event_type == "SENT"
        assert events[1].audit_id == 2
        assert events[1].event_type == "COMPLETED"

    def test_get_events_returns_empty_list(self) -> None:
        """get_events should return empty list when no events."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        logger = SyncAuditLogger(pool)
        events = logger.get_events(uuid4())

        assert events == []

    def test_get_events_with_domain_filter(self) -> None:
        """get_events should filter by domain when provided."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        logger = SyncAuditLogger(pool)
        command_id = uuid4()
        logger.get_events(command_id, domain="test")

        args = cursor.execute.call_args
        assert "AND domain = %s" in args[0][0]
        assert args[0][1] == (command_id, "test")

    def test_get_events_without_domain_filter(self) -> None:
        """get_events should not filter by domain when not provided."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        logger = SyncAuditLogger(pool)
        command_id = uuid4()
        logger.get_events(command_id)

        args = cursor.execute.call_args
        assert "AND domain = %s" not in args[0][0]
        assert args[0][1] == (command_id,)

    def test_get_events_with_provided_connection(self) -> None:
        """get_events should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        logger = SyncAuditLogger(pool)
        logger.get_events(uuid4(), conn=conn)

        pool.connection.assert_not_called()

    def test_get_events_handles_null_details(self) -> None:
        """get_events should handle null details_json."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        now = datetime.now(UTC)
        command_id = uuid4()
        rows = [
            (1, "test", command_id, "SENT", now, None),
        ]
        cursor.fetchall.return_value = rows
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        logger = SyncAuditLogger(pool)
        events = logger.get_events(command_id)

        assert events[0].details is None


class TestSyncAuditLoggerTransactionSupport:
    """Tests for transaction support across all methods."""

    def test_all_methods_support_provided_connection(self) -> None:
        """All methods should accept and use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        logger = SyncAuditLogger(pool)
        command_id = uuid4()

        # All methods with conn parameter
        logger.log("test", command_id, AuditEventType.SENT, conn=conn)
        logger.log_batch([], conn)
        logger.get_events(command_id, conn=conn)

        # Pool should never be accessed
        pool.connection.assert_not_called()
