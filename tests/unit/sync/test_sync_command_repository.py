"""Unit tests for commandbus.sync.repositories.command module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from commandbus._core.command_sql import CommandSQL
from commandbus.models import CommandMetadata, CommandStatus
from commandbus.sync.repositories.command import SyncCommandRepository


def make_metadata(
    domain: str = "test_domain",
    command_id: UUID | None = None,
    status: CommandStatus = CommandStatus.PENDING,
    attempts: int = 0,
    max_attempts: int = 3,
    batch_id: UUID | None = None,
) -> CommandMetadata:
    """Create a CommandMetadata for testing."""
    now = datetime.now(UTC)
    return CommandMetadata(
        domain=domain,
        command_id=command_id or uuid4(),
        command_type="TestCommand",
        status=status,
        attempts=attempts,
        max_attempts=max_attempts,
        msg_id=123,
        correlation_id=uuid4(),
        reply_to="reply_queue",
        last_error_type=None,
        last_error_code=None,
        last_error_msg=None,
        created_at=now,
        updated_at=now,
        batch_id=batch_id,
    )


def make_row_from_metadata(metadata: CommandMetadata) -> tuple:
    """Create a database row tuple from CommandMetadata.

    Row format matches CommandParsers.from_row expectations (15 fields):
        domain, command_id, command_type, status, attempts,
        max_attempts, msg_id, correlation_id, reply_queue,
        last_error_type, last_error_code, last_error_msg,
        created_at, updated_at, batch_id
    """
    return (
        metadata.domain,
        metadata.command_id,
        metadata.command_type,
        metadata.status.value,
        metadata.attempts,
        metadata.max_attempts,
        metadata.msg_id,
        metadata.correlation_id,
        metadata.reply_to,
        metadata.last_error_type,
        metadata.last_error_code,
        metadata.last_error_msg,
        metadata.created_at,
        metadata.updated_at,
        metadata.batch_id,
    )


class TestSyncCommandRepositoryInit:
    """Tests for SyncCommandRepository initialization."""

    def test_init_stores_pool(self) -> None:
        """SyncCommandRepository should store the pool reference."""
        pool = MagicMock()
        repo = SyncCommandRepository(pool)
        assert repo._pool is pool


class TestSyncCommandRepositorySave:
    """Tests for SyncCommandRepository.save method."""

    def test_save_with_pool(self) -> None:
        """save should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        metadata = make_metadata()
        repo.save(metadata, "test_queue")

        conn.execute.assert_called_once()
        args = conn.execute.call_args
        assert args[0][0] == CommandSQL.SAVE

    def test_save_with_provided_connection(self) -> None:
        """save should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncCommandRepository(pool)
        metadata = make_metadata()
        repo.save(metadata, "test_queue", conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_save_passes_correct_parameters(self) -> None:
        """save should pass correct parameters to SQL."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        metadata = make_metadata(domain="my_domain")
        repo.save(metadata, "my_queue")

        args = conn.execute.call_args[0][1]
        assert args[0] == "my_domain"  # domain is first param
        assert args[1] == "my_queue"  # queue_name is second


class TestSyncCommandRepositorySaveBatch:
    """Tests for SyncCommandRepository.save_batch method."""

    def test_save_batch_empty_list(self) -> None:
        """save_batch should return early for empty list."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncCommandRepository(pool)
        repo.save_batch([], "test_queue", conn)

        conn.cursor.assert_not_called()

    def test_save_batch_executes_many(self) -> None:
        """save_batch should use executemany for efficiency."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncCommandRepository(pool)
        metadata_list = [make_metadata() for _ in range(3)]
        repo.save_batch(metadata_list, "test_queue", conn)

        cursor.executemany.assert_called_once()
        args = cursor.executemany.call_args
        assert args[0][0] == CommandSQL.SAVE
        assert len(args[0][1]) == 3


class TestSyncCommandRepositoryExistsBatch:
    """Tests for SyncCommandRepository.exists_batch method."""

    def test_exists_batch_empty_list(self) -> None:
        """exists_batch should return empty set for empty input."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncCommandRepository(pool)
        result = repo.exists_batch("domain", [], conn)

        assert result == set()
        conn.cursor.assert_not_called()

    def test_exists_batch_returns_existing_ids(self) -> None:
        """exists_batch should return set of existing command IDs."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        id1 = uuid4()
        id2 = uuid4()
        cursor.fetchall.return_value = [(id1,), (id2,)]
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncCommandRepository(pool)
        id3 = uuid4()
        result = repo.exists_batch("domain", [id1, id2, id3], conn)

        assert result == {id1, id2}

    def test_exists_batch_executes_correct_sql(self) -> None:
        """exists_batch should execute EXISTS_BATCH SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncCommandRepository(pool)
        ids = [uuid4(), uuid4()]
        repo.exists_batch("my_domain", ids, conn)

        args = cursor.execute.call_args
        assert args[0][0] == CommandSQL.EXISTS_BATCH
        assert args[0][1][0] == "my_domain"


class TestSyncCommandRepositoryGet:
    """Tests for SyncCommandRepository.get method."""

    def test_get_returns_metadata_when_found(self) -> None:
        """get should return CommandMetadata when found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        metadata = make_metadata()
        cursor.fetchone.return_value = make_row_from_metadata(metadata)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.get("test_domain", metadata.command_id)

        assert result is not None
        assert result.command_id == metadata.command_id

    def test_get_returns_none_when_not_found(self) -> None:
        """get should return None when command not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
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

        repo = SyncCommandRepository(pool)
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

        repo = SyncCommandRepository(pool)
        cmd_id = uuid4()
        repo.get("my_domain", cmd_id)

        args = cursor.execute.call_args
        assert args[0][0] == CommandSQL.GET
        assert args[0][1] == ("my_domain", cmd_id)


class TestSyncCommandRepositoryUpdateStatus:
    """Tests for SyncCommandRepository.update_status method."""

    def test_update_status_with_pool(self) -> None:
        """update_status should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.update_status("domain", uuid4(), CommandStatus.IN_PROGRESS)

        conn.execute.assert_called_once()

    def test_update_status_with_provided_connection(self) -> None:
        """update_status should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncCommandRepository(pool)
        repo.update_status("domain", uuid4(), CommandStatus.COMPLETED, conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_update_status_executes_correct_sql(self) -> None:
        """update_status should execute UPDATE_STATUS SQL."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.update_status("domain", uuid4(), CommandStatus.FAILED)

        args = conn.execute.call_args
        assert args[0][0] == CommandSQL.UPDATE_STATUS


class TestSyncCommandRepositoryUpdateMsgId:
    """Tests for SyncCommandRepository.update_msg_id method."""

    def test_update_msg_id_with_pool(self) -> None:
        """update_msg_id should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.update_msg_id("domain", uuid4(), 456)

        conn.execute.assert_called_once()

    def test_update_msg_id_with_provided_connection(self) -> None:
        """update_msg_id should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncCommandRepository(pool)
        repo.update_msg_id("domain", uuid4(), 789, conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_update_msg_id_executes_correct_sql(self) -> None:
        """update_msg_id should execute UPDATE_MSG_ID SQL."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.update_msg_id("domain", uuid4(), 999)

        args = conn.execute.call_args
        assert args[0][0] == CommandSQL.UPDATE_MSG_ID


class TestSyncCommandRepositoryIncrementAttempts:
    """Tests for SyncCommandRepository.increment_attempts method."""

    def test_increment_attempts_returns_new_value(self) -> None:
        """increment_attempts should return new attempts value."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (5,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.increment_attempts("domain", uuid4())

        assert result == 5

    def test_increment_attempts_returns_zero_when_not_found(self) -> None:
        """increment_attempts should return 0 when command not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.increment_attempts("domain", uuid4())

        assert result == 0

    def test_increment_attempts_with_provided_connection(self) -> None:
        """increment_attempts should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (2,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncCommandRepository(pool)
        repo.increment_attempts("domain", uuid4(), conn=conn)

        pool.connection.assert_not_called()

    def test_increment_attempts_executes_correct_sql(self) -> None:
        """increment_attempts should execute INCREMENT_ATTEMPTS SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (1,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        cmd_id = uuid4()
        repo.increment_attempts("my_domain", cmd_id)

        args = cursor.execute.call_args
        assert args[0][0] == CommandSQL.INCREMENT_ATTEMPTS
        assert args[0][1] == ("my_domain", cmd_id)


class TestSyncCommandRepositoryReceiveCommand:
    """Tests for SyncCommandRepository.receive_command method."""

    def test_receive_command_returns_metadata_and_attempts(self) -> None:
        """receive_command should return tuple of metadata and attempts."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        metadata = make_metadata(attempts=3)
        cursor.fetchone.return_value = make_row_from_metadata(metadata)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.receive_command("domain", metadata.command_id)

        assert result is not None
        assert result[0].command_id == metadata.command_id
        assert result[1] == 3

    def test_receive_command_returns_none_when_not_found(self) -> None:
        """receive_command should return None when command not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.receive_command("domain", uuid4())

        assert result is None

    def test_receive_command_with_provided_connection(self) -> None:
        """receive_command should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncCommandRepository(pool)
        repo.receive_command("domain", uuid4(), conn=conn)

        pool.connection.assert_not_called()

    def test_receive_command_uses_custom_status(self) -> None:
        """receive_command should use provided status."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.receive_command("domain", uuid4(), new_status=CommandStatus.PENDING)

        args = cursor.execute.call_args
        # Status is first param in params tuple
        assert CommandStatus.PENDING.value in args[0][1]


class TestSyncCommandRepositoryUpdateError:
    """Tests for SyncCommandRepository.update_error method."""

    def test_update_error_with_pool(self) -> None:
        """update_error should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.update_error("domain", uuid4(), "TRANSIENT", "TIMEOUT", "Connection timeout")

        conn.execute.assert_called_once()

    def test_update_error_with_provided_connection(self) -> None:
        """update_error should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncCommandRepository(pool)
        repo.update_error(
            "domain", uuid4(), "PERMANENT", "NOT_FOUND", "Resource not found", conn=conn
        )

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_update_error_executes_correct_sql(self) -> None:
        """update_error should execute UPDATE_ERROR SQL."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.update_error("domain", uuid4(), "TRANSIENT", "DB_ERROR", "Database error")

        args = conn.execute.call_args
        assert args[0][0] == CommandSQL.UPDATE_ERROR


class TestSyncCommandRepositoryFinishCommand:
    """Tests for SyncCommandRepository.finish_command method."""

    def test_finish_command_with_pool(self) -> None:
        """finish_command should use pool when no connection provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.finish_command("domain", uuid4(), CommandStatus.COMPLETED)

        conn.execute.assert_called_once()

    def test_finish_command_with_provided_connection(self) -> None:
        """finish_command should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()

        repo = SyncCommandRepository(pool)
        repo.finish_command("domain", uuid4(), CommandStatus.FAILED, conn=conn)

        conn.execute.assert_called_once()
        pool.connection.assert_not_called()

    def test_finish_command_with_error_info(self) -> None:
        """finish_command should pass error info when provided."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.finish_command(
            "domain",
            uuid4(),
            CommandStatus.FAILED,
            error_type="PERMANENT",
            error_code="INVALID",
            error_msg="Invalid input",
        )

        args = conn.execute.call_args
        assert args[0][0] == CommandSQL.FINISH_COMMAND

    def test_finish_command_without_error_info(self) -> None:
        """finish_command should work without error info."""
        pool = MagicMock()
        conn = MagicMock()
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.finish_command("domain", uuid4(), CommandStatus.COMPLETED)

        conn.execute.assert_called_once()


class TestSyncCommandRepositoryExists:
    """Tests for SyncCommandRepository.exists method."""

    def test_exists_returns_true_when_found(self) -> None:
        """exists should return True when command exists."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.exists("domain", uuid4())

        assert result is True

    def test_exists_returns_false_when_not_found(self) -> None:
        """exists should return False when command not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
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

        repo = SyncCommandRepository(pool)
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

        repo = SyncCommandRepository(pool)
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

        repo = SyncCommandRepository(pool)
        cmd_id = uuid4()
        repo.exists("my_domain", cmd_id)

        args = cursor.execute.call_args
        assert args[0][0] == CommandSQL.EXISTS
        assert args[0][1] == ("my_domain", cmd_id)


class TestSyncCommandRepositoryListByBatch:
    """Tests for SyncCommandRepository.list_by_batch method."""

    def test_list_by_batch_returns_metadata_list(self) -> None:
        """list_by_batch should return list of CommandMetadata."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        batch_id = uuid4()
        metadata1 = make_metadata(batch_id=batch_id)
        metadata2 = make_metadata(batch_id=batch_id)
        cursor.fetchall.return_value = [
            make_row_from_metadata(metadata1),
            make_row_from_metadata(metadata2),
        ]
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.list_by_batch("domain", batch_id)

        assert len(result) == 2
        assert all(isinstance(m, CommandMetadata) for m in result)

    def test_list_by_batch_empty_result(self) -> None:
        """list_by_batch should return empty list when no commands found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.list_by_batch("domain", uuid4())

        assert result == []

    def test_list_by_batch_with_status_filter(self) -> None:
        """list_by_batch should use status filter SQL when provided."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.list_by_batch("domain", uuid4(), status=CommandStatus.COMPLETED)

        args = cursor.execute.call_args
        assert args[0][0] == CommandSQL.LIST_BY_BATCH_WITH_STATUS

    def test_list_by_batch_without_status_filter(self) -> None:
        """list_by_batch should use regular SQL when no status provided."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.list_by_batch("domain", uuid4())

        args = cursor.execute.call_args
        assert args[0][0] == CommandSQL.LIST_BY_BATCH

    def test_list_by_batch_with_limit_and_offset(self) -> None:
        """list_by_batch should pass limit and offset to SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        batch_id = uuid4()
        repo.list_by_batch("domain", batch_id, limit=50, offset=10)

        args = cursor.execute.call_args[0][1]
        assert args[2] == 50  # limit
        assert args[3] == 10  # offset

    def test_list_by_batch_with_provided_connection(self) -> None:
        """list_by_batch should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncCommandRepository(pool)
        repo.list_by_batch("domain", uuid4(), conn=conn)

        pool.connection.assert_not_called()


class TestSyncCommandRepositorySpReceiveCommand:
    """Tests for SyncCommandRepository.sp_receive_command method."""

    def test_sp_receive_command_returns_metadata_and_attempts(self) -> None:
        """sp_receive_command should return tuple of metadata and attempts."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        metadata = make_metadata(attempts=2)
        cursor.fetchone.return_value = make_row_from_metadata(metadata)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.sp_receive_command("domain", metadata.command_id, msg_id=456)

        assert result is not None
        assert result[0].command_id == metadata.command_id
        assert result[1] == 2

    def test_sp_receive_command_returns_none_when_not_found(self) -> None:
        """sp_receive_command should return None when command not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.sp_receive_command("domain", uuid4())

        assert result is None

    def test_sp_receive_command_with_provided_connection(self) -> None:
        """sp_receive_command should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncCommandRepository(pool)
        repo.sp_receive_command("domain", uuid4(), conn=conn)

        pool.connection.assert_not_called()

    def test_sp_receive_command_executes_correct_sql(self) -> None:
        """sp_receive_command should execute SP_RECEIVE_COMMAND SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.sp_receive_command("domain", uuid4(), msg_id=100, max_attempts=5)

        args = cursor.execute.call_args
        assert args[0][0] == CommandSQL.SP_RECEIVE_COMMAND


class TestSyncCommandRepositorySpFinishCommand:
    """Tests for SyncCommandRepository.sp_finish_command method."""

    def test_sp_finish_command_returns_true_when_batch_complete(self) -> None:
        """sp_finish_command should return True when batch is complete."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.sp_finish_command("domain", uuid4(), CommandStatus.COMPLETED, "COMPLETED")

        assert result is True

    def test_sp_finish_command_returns_false_when_batch_not_complete(self) -> None:
        """sp_finish_command should return False when batch not complete."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.sp_finish_command("domain", uuid4(), CommandStatus.COMPLETED, "COMPLETED")

        assert result is False

    def test_sp_finish_command_returns_false_on_no_row(self) -> None:
        """sp_finish_command should return False when no row returned."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.sp_finish_command("domain", uuid4(), CommandStatus.COMPLETED, "COMPLETED")

        assert result is False

    def test_sp_finish_command_with_error_info(self) -> None:
        """sp_finish_command should pass error info."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.sp_finish_command(
            "domain",
            uuid4(),
            CommandStatus.FAILED,
            "MOVED_TO_TSQ",
            error_type="PERMANENT",
            error_code="INVALID",
            error_msg="Invalid data",
        )

        cursor.execute.assert_called_once()

    def test_sp_finish_command_with_details(self) -> None:
        """sp_finish_command should JSON encode details."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.sp_finish_command(
            "domain",
            uuid4(),
            CommandStatus.COMPLETED,
            "COMPLETED",
            details={"key": "value"},
        )

        cursor.execute.assert_called_once()

    def test_sp_finish_command_with_batch_id(self) -> None:
        """sp_finish_command should pass batch_id."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        batch_id = uuid4()
        repo.sp_finish_command(
            "domain", uuid4(), CommandStatus.COMPLETED, "COMPLETED", batch_id=batch_id
        )

        cursor.execute.assert_called_once()

    def test_sp_finish_command_with_provided_connection(self) -> None:
        """sp_finish_command should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncCommandRepository(pool)
        repo.sp_finish_command("domain", uuid4(), CommandStatus.COMPLETED, "COMPLETED", conn=conn)

        pool.connection.assert_not_called()

    def test_sp_finish_command_executes_correct_sql(self) -> None:
        """sp_finish_command should execute SP_FINISH_COMMAND SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.sp_finish_command("domain", uuid4(), CommandStatus.COMPLETED, "COMPLETED")

        args = cursor.execute.call_args
        assert args[0][0] == CommandSQL.SP_FINISH_COMMAND


class TestSyncCommandRepositorySpFailCommand:
    """Tests for SyncCommandRepository.sp_fail_command method."""

    def test_sp_fail_command_returns_true_on_success(self) -> None:
        """sp_fail_command should return True when command found and updated."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.sp_fail_command(
            "domain", uuid4(), "TRANSIENT", "TIMEOUT", "Timeout", 1, 3, 123
        )

        assert result is True

    def test_sp_fail_command_returns_false_when_not_found(self) -> None:
        """sp_fail_command should return False when command not found."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.sp_fail_command(
            "domain", uuid4(), "PERMANENT", "INVALID", "Invalid", 1, 3, 123
        )

        assert result is False

    def test_sp_fail_command_returns_false_on_no_row(self) -> None:
        """sp_fail_command should return False when no row returned."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        result = repo.sp_fail_command("domain", uuid4(), "TRANSIENT", "ERROR", "Error", 1, 3, 123)

        assert result is False

    def test_sp_fail_command_with_provided_connection(self) -> None:
        """sp_fail_command should use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncCommandRepository(pool)
        repo.sp_fail_command("domain", uuid4(), "TRANSIENT", "ERROR", "Error", 1, 3, 123, conn=conn)

        pool.connection.assert_not_called()

    def test_sp_fail_command_executes_correct_sql(self) -> None:
        """sp_fail_command should execute SP_FAIL_COMMAND SQL."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        cursor.fetchone.return_value = (True,)
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor
        pool.connection.return_value.__enter__ = MagicMock(return_value=conn)
        pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        repo = SyncCommandRepository(pool)
        repo.sp_fail_command("domain", uuid4(), "TRANSIENT", "TIMEOUT", "Timeout", 2, 5, 456)

        args = cursor.execute.call_args
        assert args[0][0] == CommandSQL.SP_FAIL_COMMAND


class TestSyncCommandRepositoryTransactionSupport:
    """Tests for transaction support across all methods."""

    def test_all_optional_conn_methods_support_provided_connection(self) -> None:
        """All methods with optional conn should accept and use provided connection."""
        pool = MagicMock()
        conn = MagicMock()
        cursor = MagicMock()
        # Use None for fetchone to avoid parsing issues, and (1,) for increment_attempts
        # The key is that pool.connection() is never called
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        cursor.__enter__ = MagicMock(return_value=cursor)
        cursor.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cursor

        repo = SyncCommandRepository(pool)
        metadata = make_metadata()

        # Methods that use conn.execute directly (no cursor needed)
        repo.save(metadata, "q", conn=conn)
        repo.update_status("domain", uuid4(), CommandStatus.COMPLETED, conn=conn)
        repo.update_msg_id("domain", uuid4(), 123, conn=conn)
        repo.update_error("domain", uuid4(), "T", "C", "M", conn=conn)
        repo.finish_command("domain", uuid4(), CommandStatus.COMPLETED, conn=conn)

        # Methods that use cursor but return None is fine
        repo.get("domain", uuid4(), conn=conn)
        repo.receive_command("domain", uuid4(), conn=conn)
        repo.sp_receive_command("domain", uuid4(), conn=conn)

        # For increment_attempts, we need a value returned
        cursor.fetchone.return_value = (1,)
        repo.increment_attempts("domain", uuid4(), conn=conn)

        # For exists, we need a boolean tuple
        cursor.fetchone.return_value = (True,)
        repo.exists("domain", uuid4(), conn=conn)

        # For sp_finish_command and sp_fail_command, we need a boolean tuple
        cursor.fetchone.return_value = (False,)
        repo.sp_finish_command("domain", uuid4(), CommandStatus.COMPLETED, "E", conn=conn)
        repo.sp_fail_command("domain", uuid4(), "T", "C", "M", 1, 3, 1, conn=conn)

        # list_by_batch uses fetchall
        repo.list_by_batch("domain", uuid4(), conn=conn)

        # Pool should never be accessed
        pool.connection.assert_not_called()
