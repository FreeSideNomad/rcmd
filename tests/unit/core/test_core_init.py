"""Unit tests for commandbus._core module initialization."""

from commandbus._core import (
    BatchParams,
    BatchParsers,
    BatchSQL,
    CommandParams,
    CommandParsers,
    CommandSQL,
    PgmqParams,
    PgmqParsers,
    PgmqSQL,
)


class TestCoreModuleExports:
    """Tests for _core module exports."""

    def test_command_sql_exported(self) -> None:
        """CommandSQL should be exported from _core."""
        assert CommandSQL is not None
        assert hasattr(CommandSQL, "SAVE")

    def test_command_params_exported(self) -> None:
        """CommandParams should be exported from _core."""
        assert CommandParams is not None
        assert hasattr(CommandParams, "save")

    def test_command_parsers_exported(self) -> None:
        """CommandParsers should be exported from _core."""
        assert CommandParsers is not None
        assert hasattr(CommandParsers, "from_row")

    def test_batch_sql_exported(self) -> None:
        """BatchSQL should be exported from _core."""
        assert BatchSQL is not None
        assert hasattr(BatchSQL, "SAVE")

    def test_batch_params_exported(self) -> None:
        """BatchParams should be exported from _core."""
        assert BatchParams is not None
        assert hasattr(BatchParams, "save")

    def test_batch_parsers_exported(self) -> None:
        """BatchParsers should be exported from _core."""
        assert BatchParsers is not None
        assert hasattr(BatchParsers, "from_row")

    def test_pgmq_sql_exported(self) -> None:
        """PgmqSQL should be exported from _core."""
        assert PgmqSQL is not None
        assert hasattr(PgmqSQL, "SEND")

    def test_pgmq_params_exported(self) -> None:
        """PgmqParams should be exported from _core."""
        assert PgmqParams is not None
        assert hasattr(PgmqParams, "send")

    def test_pgmq_parsers_exported(self) -> None:
        """PgmqParsers should be exported from _core."""
        assert PgmqParsers is not None
        assert hasattr(PgmqParsers, "from_row")
