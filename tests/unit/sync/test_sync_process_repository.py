"""Unit tests for commandbus.sync.repositories.process module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from commandbus._core.process_sql import ProcessSQL
from commandbus.models import ReplyOutcome
from commandbus.process.models import (
    ProcessAuditEntry,
    ProcessMetadata,
    ProcessStatus,
)
from commandbus.sync.repositories.process import SyncProcessRepository


def make_process_metadata(
    domain: str = "test",
    process_id: str | None = None,
    process_type: str = "TestProcess",
    status: ProcessStatus = ProcessStatus.PENDING,
    current_step: str = "step1",
) -> ProcessMetadata:
    """Create a ProcessMetadata for testing."""
    now = datetime.now(UTC)
    return ProcessMetadata(
        domain=domain,
        process_id=uuid4() if process_id is None else process_id,
        process_type=process_type,
        status=status,
        current_step=current_step,
        state={"key": "value"},
        error_code=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
    )


def make_audit_entry(
    step_name: str = "step1",
    reply_outcome: ReplyOutcome | None = None,
) -> ProcessAuditEntry:
    """Create a ProcessAuditEntry for testing."""
    now = datetime.now(UTC)
    return ProcessAuditEntry(
        step_name=step_name,
        command_id=uuid4(),
        command_type="TestCommand",
        command_data={"key": "value"},
        sent_at=now,
        reply_outcome=reply_outcome,
        reply_data={"result": "ok"} if reply_outcome else None,
        received_at=now if reply_outcome else None,
    )


def make_row_from_process(process: ProcessMetadata) -> tuple:
    """Create a database row tuple from ProcessMetadata."""
    return (
        process.domain,
        process.process_id,
        process.process_type,
        process.status.value,
        process.current_step,
        process.state,
        process.error_code,
        process.error_message,
        process.created_at,
        process.updated_at,
        process.completed_at,
    )


def make_row_from_audit_entry(entry: ProcessAuditEntry) -> tuple:
    """Create a database row tuple from ProcessAuditEntry."""
    return (
        entry.step_name,
        entry.command_id,
        entry.command_type,
        entry.command_data,
        entry.sent_at,
        entry.reply_outcome.value if entry.reply_outcome else None,
        entry.reply_data,
        entry.received_at,
    )


class TestSyncProcessRepositoryInit:
    """Tests for SyncProcessRepository initialization."""

    def test_init_stores_pool(self) -> None:
        """SyncProcessRepository should store the pool reference."""
        pool = MagicMock()
        repo = SyncProcessRepository(pool)
        assert repo._pool is pool


class TestSyncProcessRepositorySave:
    """Tests for SyncProcessRepository.save method."""

    def test_save_with_pool(self) -> None:
        """save should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        process = make_process_metadata()
        repo.save(process)

        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert args[0][0] == ProcessSQL.SAVE

    def test_save_with_provided_connection(self) -> None:
        """save should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncProcessRepository(pool)
        process = make_process_metadata()
        repo.save(process, conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_save_serializes_state(self) -> None:
        """save should serialize state to JSON."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        process = make_process_metadata()
        repo.save(process)

        args = conn.execute.call_args
        params = args[0][1]
        # Verify state is serialized (6th param, index 5)
        assert '"key"' in params[5]  # JSON string contains key

    def test_save_with_to_dict_state(self) -> None:
        """save should call to_dict() on state if available."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        state_obj = MagicMock()
        state_obj.to_dict.return_value = {"custom": "state"}

        repo = SyncProcessRepository(pool)
        process = make_process_metadata()
        process.state = state_obj
        repo.save(process)

        state_obj.to_dict.assert_called_once()


class TestSyncProcessRepositoryUpdate:
    """Tests for SyncProcessRepository.update method."""

    def test_update_with_pool(self) -> None:
        """update should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        process = make_process_metadata(status=ProcessStatus.IN_PROGRESS)
        repo.update(process)

        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert args[0][0] == ProcessSQL.UPDATE

    def test_update_with_provided_connection(self) -> None:
        """update should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncProcessRepository(pool)
        process = make_process_metadata()
        repo.update(process, conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_update_serializes_state(self) -> None:
        """update should serialize state to JSON."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        process = make_process_metadata()
        repo.update(process)

        args = conn.execute.call_args
        params = args[0][1]
        # Verify state is serialized (3rd param, index 2)
        assert '"key"' in params[2]

    def test_update_with_to_dict_state(self) -> None:
        """update should call to_dict() on state if available."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        state_obj = MagicMock()
        state_obj.to_dict.return_value = {"custom": "state"}

        repo = SyncProcessRepository(pool)
        process = make_process_metadata()
        process.state = state_obj
        repo.update(process)

        state_obj.to_dict.assert_called_once()


class TestSyncProcessRepositoryGetById:
    """Tests for SyncProcessRepository.get_by_id method."""

    def test_get_by_id_returns_process(self) -> None:
        """get_by_id should return ProcessMetadata when found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()

        process = make_process_metadata()
        row = make_row_from_process(process)
        cursor.fetchone.return_value = row
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        result = repo.get_by_id("test", process.process_id)

        assert result is not None
        assert result.domain == process.domain
        assert result.process_id == process.process_id
        assert result.process_type == process.process_type

    def test_get_by_id_returns_none_when_not_found(self) -> None:
        """get_by_id should return None when process not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        result = repo.get_by_id("test", uuid4())

        assert result is None

    def test_get_by_id_executes_correct_sql(self) -> None:
        """get_by_id should execute GET_BY_ID SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        process_id = uuid4()
        repo.get_by_id("test", process_id)

        args = cursor.execute.call_args
        assert args[0][0] == ProcessSQL.GET_BY_ID
        assert args[0][1] == ("test", process_id)

    def test_get_by_id_with_provided_connection(self) -> None:
        """get_by_id should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncProcessRepository(pool)
        repo.get_by_id("test", uuid4(), conn=conn)

        pool.connection.assert_not_called()


class TestSyncProcessRepositoryFindByStatus:
    """Tests for SyncProcessRepository.find_by_status method."""

    def test_find_by_status_returns_list(self) -> None:
        """find_by_status should return list of ProcessMetadata."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()

        process1 = make_process_metadata()
        process2 = make_process_metadata()
        rows = [make_row_from_process(process1), make_row_from_process(process2)]
        cursor.fetchall.return_value = rows
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        result = repo.find_by_status("test", [ProcessStatus.PENDING])

        assert len(result) == 2
        assert all(isinstance(p, ProcessMetadata) for p in result)

    def test_find_by_status_returns_empty_list(self) -> None:
        """find_by_status should return empty list when no matches."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        result = repo.find_by_status("test", [ProcessStatus.COMPLETED])

        assert result == []

    def test_find_by_status_executes_correct_sql(self) -> None:
        """find_by_status should execute FIND_BY_STATUS SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        repo.find_by_status("test", [ProcessStatus.PENDING, ProcessStatus.IN_PROGRESS])

        args = cursor.execute.call_args
        assert args[0][0] == ProcessSQL.FIND_BY_STATUS
        assert args[0][1] == ("test", ["PENDING", "IN_PROGRESS"])

    def test_find_by_status_with_provided_connection(self) -> None:
        """find_by_status should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncProcessRepository(pool)
        repo.find_by_status("test", [ProcessStatus.PENDING], conn=conn)

        pool.connection.assert_not_called()


class TestSyncProcessRepositoryLogStep:
    """Tests for SyncProcessRepository.log_step method."""

    def test_log_step_with_pool(self) -> None:
        """log_step should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        entry = make_audit_entry()
        repo.log_step("test", uuid4(), entry)

        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert args[0][0] == ProcessSQL.LOG_STEP

    def test_log_step_with_provided_connection(self) -> None:
        """log_step should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncProcessRepository(pool)
        entry = make_audit_entry()
        repo.log_step("test", uuid4(), entry, conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_log_step_includes_reply_outcome(self) -> None:
        """log_step should include reply_outcome when present."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        entry = make_audit_entry(reply_outcome=ReplyOutcome.SUCCESS)
        repo.log_step("test", uuid4(), entry)

        args = conn.execute.call_args
        params = args[0][1]
        # reply_outcome is at index 7
        assert params[7] == "SUCCESS"


class TestSyncProcessRepositoryUpdateStepReply:
    """Tests for SyncProcessRepository.update_step_reply method."""

    def test_update_step_reply_with_pool(self) -> None:
        """update_step_reply should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        entry = make_audit_entry(reply_outcome=ReplyOutcome.SUCCESS)
        repo.update_step_reply("test", uuid4(), uuid4(), entry)

        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert args[0][0] == ProcessSQL.UPDATE_STEP_REPLY

    def test_update_step_reply_with_provided_connection(self) -> None:
        """update_step_reply should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncProcessRepository(pool)
        entry = make_audit_entry(reply_outcome=ReplyOutcome.SUCCESS)
        repo.update_step_reply("test", uuid4(), uuid4(), entry, conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_update_step_reply_params(self) -> None:
        """update_step_reply should pass correct parameters."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        entry = make_audit_entry(reply_outcome=ReplyOutcome.FAILED)
        process_id = uuid4()
        command_id = uuid4()
        repo.update_step_reply("test", process_id, command_id, entry)

        args = conn.execute.call_args
        params = args[0][1]
        assert params[0] == "FAILED"  # reply_outcome
        assert params[3] == "test"  # domain
        assert params[4] == process_id
        assert params[5] == command_id


class TestSyncProcessRepositoryGetAuditTrail:
    """Tests for SyncProcessRepository.get_audit_trail method."""

    def test_get_audit_trail_returns_list(self) -> None:
        """get_audit_trail should return list of ProcessAuditEntry."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()

        entry1 = make_audit_entry("step1")
        entry2 = make_audit_entry("step2", reply_outcome=ReplyOutcome.SUCCESS)
        rows = [
            make_row_from_audit_entry(entry1),
            make_row_from_audit_entry(entry2),
        ]
        cursor.fetchall.return_value = rows
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        result = repo.get_audit_trail("test", uuid4())

        assert len(result) == 2
        assert all(isinstance(e, ProcessAuditEntry) for e in result)
        assert result[0].step_name == "step1"
        assert result[1].step_name == "step2"

    def test_get_audit_trail_returns_empty_list(self) -> None:
        """get_audit_trail should return empty list when no entries."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        result = repo.get_audit_trail("test", uuid4())

        assert result == []

    def test_get_audit_trail_executes_correct_sql(self) -> None:
        """get_audit_trail should execute GET_AUDIT_TRAIL SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        process_id = uuid4()
        repo.get_audit_trail("test", process_id)

        args = cursor.execute.call_args
        assert args[0][0] == ProcessSQL.GET_AUDIT_TRAIL
        assert args[0][1] == ("test", process_id)

    def test_get_audit_trail_with_provided_connection(self) -> None:
        """get_audit_trail should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncProcessRepository(pool)
        repo.get_audit_trail("test", uuid4(), conn=conn)

        pool.connection.assert_not_called()


class TestSyncProcessRepositoryGetCompletedSteps:
    """Tests for SyncProcessRepository.get_completed_steps method."""

    def test_get_completed_steps_returns_list(self) -> None:
        """get_completed_steps should return list of step names."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = [("step1",), ("step2",), ("step3",)]
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        result = repo.get_completed_steps("test", uuid4())

        assert result == ["step1", "step2", "step3"]

    def test_get_completed_steps_returns_empty_list(self) -> None:
        """get_completed_steps should return empty list when no completed steps."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        result = repo.get_completed_steps("test", uuid4())

        assert result == []

    def test_get_completed_steps_executes_correct_sql(self) -> None:
        """get_completed_steps should execute GET_COMPLETED_STEPS SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncProcessRepository(pool)
        process_id = uuid4()
        repo.get_completed_steps("test", process_id)

        args = cursor.execute.call_args
        assert args[0][0] == ProcessSQL.GET_COMPLETED_STEPS
        assert args[0][1] == ("test", process_id)

    def test_get_completed_steps_with_provided_connection(self) -> None:
        """get_completed_steps should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncProcessRepository(pool)
        repo.get_completed_steps("test", uuid4(), conn=conn)

        pool.connection.assert_not_called()


class TestSyncProcessRepositoryTransactionSupport:
    """Tests for transaction support across all methods."""

    def test_all_methods_support_provided_connection(self) -> None:
        """All methods should accept and use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncProcessRepository(pool)
        process = make_process_metadata()
        entry = make_audit_entry(reply_outcome=ReplyOutcome.SUCCESS)

        # All methods with conn parameter
        repo.save(process, conn=conn)
        repo.update(process, conn=conn)
        repo.get_by_id("test", uuid4(), conn=conn)
        repo.find_by_status("test", [ProcessStatus.PENDING], conn=conn)
        repo.log_step("test", uuid4(), entry, conn=conn)
        repo.update_step_reply("test", uuid4(), uuid4(), entry, conn=conn)
        repo.get_audit_trail("test", uuid4(), conn=conn)
        repo.get_completed_steps("test", uuid4(), conn=conn)

        # Pool should never be accessed
        pool.connection.assert_not_called()
