"""Unit tests for commandbus.sync.timeouts module."""

import pytest
from psycopg import errors as psycopg_errors
from psycopg_pool import PoolTimeout

from commandbus.sync.timeouts import (
    DEFAULT_POOL_TIMEOUT_S,
    DEFAULT_STATEMENT_TIMEOUT_MS,
    DEFAULT_VISIBILITY_TIMEOUT_S,
    DEFAULT_WATCHDOG_INTERVAL_S,
    STUCK_THREAD_BUFFER_S,
    TimeoutConfig,
    is_pool_timeout,
    is_query_cancelled,
    is_timeout_error,
    validate_timeouts,
)


class TestTimeoutDefaults:
    """Tests for timeout default values."""

    def test_default_statement_timeout(self) -> None:
        """Should have default statement timeout of 25s."""
        assert DEFAULT_STATEMENT_TIMEOUT_MS == 25000

    def test_default_visibility_timeout(self) -> None:
        """Should have default visibility timeout of 30s."""
        assert DEFAULT_VISIBILITY_TIMEOUT_S == 30

    def test_default_pool_timeout(self) -> None:
        """Should have default pool timeout of 30s."""
        assert DEFAULT_POOL_TIMEOUT_S == 30.0

    def test_default_watchdog_interval(self) -> None:
        """Should have default watchdog interval of 10s."""
        assert DEFAULT_WATCHDOG_INTERVAL_S == 10.0

    def test_stuck_thread_buffer(self) -> None:
        """Should have stuck thread buffer of 5s."""
        assert STUCK_THREAD_BUFFER_S == 5.0


class TestTimeoutConfig:
    """Tests for TimeoutConfig dataclass."""

    def test_default_values(self) -> None:
        """Should use default values when not specified."""
        config = TimeoutConfig()

        assert config.statement_timeout_ms == DEFAULT_STATEMENT_TIMEOUT_MS
        assert config.visibility_timeout_s == DEFAULT_VISIBILITY_TIMEOUT_S
        assert config.pool_timeout_s == DEFAULT_POOL_TIMEOUT_S
        assert config.watchdog_interval_s == DEFAULT_WATCHDOG_INTERVAL_S

    def test_custom_values(self) -> None:
        """Should accept custom values."""
        config = TimeoutConfig(
            statement_timeout_ms=10000,
            visibility_timeout_s=20,
            pool_timeout_s=15.0,
            watchdog_interval_s=5.0,
        )

        assert config.statement_timeout_ms == 10000
        assert config.visibility_timeout_s == 20
        assert config.pool_timeout_s == 15.0
        assert config.watchdog_interval_s == 5.0

    def test_statement_timeout_seconds_property(self) -> None:
        """Should convert statement timeout to seconds."""
        config = TimeoutConfig(statement_timeout_ms=25000)

        assert config.statement_timeout_s == 25.0

    def test_stuck_threshold_property(self) -> None:
        """Should calculate stuck threshold."""
        config = TimeoutConfig(visibility_timeout_s=30)

        assert config.stuck_threshold_s == 35.0

    def test_immutable(self) -> None:
        """Should be immutable (frozen dataclass)."""
        config = TimeoutConfig()

        with pytest.raises(AttributeError):
            config.statement_timeout_ms = 10000  # type: ignore[misc]


class TestTimeoutConfigValidation:
    """Tests for TimeoutConfig.validate method."""

    def test_validate_default_config(self) -> None:
        """Should pass with default values."""
        config = TimeoutConfig()
        config.validate()  # Should not raise

    def test_validate_statement_less_than_visibility(self) -> None:
        """Should pass when statement < visibility."""
        config = TimeoutConfig(
            statement_timeout_ms=10000,  # 10s
            visibility_timeout_s=20,  # 20s
        )
        config.validate()  # Should not raise

    def test_validate_statement_equal_visibility_fails(self) -> None:
        """Should fail when statement == visibility."""
        config = TimeoutConfig(
            statement_timeout_ms=30000,  # 30s
            visibility_timeout_s=30,  # 30s
        )

        with pytest.raises(ValueError, match="must be less than"):
            config.validate()

    def test_validate_statement_greater_visibility_fails(self) -> None:
        """Should fail when statement > visibility."""
        config = TimeoutConfig(
            statement_timeout_ms=40000,  # 40s
            visibility_timeout_s=30,  # 30s
        )

        with pytest.raises(ValueError, match="must be less than"):
            config.validate()

    def test_validate_negative_statement_timeout_fails(self) -> None:
        """Should fail with negative statement timeout."""
        config = TimeoutConfig(statement_timeout_ms=-1)

        with pytest.raises(ValueError, match="statement_timeout_ms must be positive"):
            config.validate()

    def test_validate_zero_statement_timeout_fails(self) -> None:
        """Should fail with zero statement timeout."""
        config = TimeoutConfig(statement_timeout_ms=0)

        with pytest.raises(ValueError, match="statement_timeout_ms must be positive"):
            config.validate()

    def test_validate_negative_visibility_timeout_fails(self) -> None:
        """Should fail with negative visibility timeout."""
        config = TimeoutConfig(visibility_timeout_s=-1)

        with pytest.raises(ValueError, match="visibility_timeout_s must be positive"):
            config.validate()

    def test_validate_negative_pool_timeout_fails(self) -> None:
        """Should fail with negative pool timeout."""
        config = TimeoutConfig(pool_timeout_s=-1.0)

        with pytest.raises(ValueError, match="pool_timeout_s must be positive"):
            config.validate()

    def test_validate_negative_watchdog_interval_fails(self) -> None:
        """Should fail with negative watchdog interval."""
        config = TimeoutConfig(watchdog_interval_s=-1.0)

        with pytest.raises(ValueError, match="watchdog_interval_s must be positive"):
            config.validate()


class TestValidateTimeouts:
    """Tests for validate_timeouts function."""

    def test_validate_defaults(self) -> None:
        """Should pass with default values."""
        validate_timeouts()  # Should not raise

    def test_validate_valid_timeouts(self) -> None:
        """Should pass with valid timeouts."""
        validate_timeouts(
            statement_timeout_ms=10000,
            visibility_timeout_s=20,
        )  # Should not raise

    def test_validate_invalid_timeouts(self) -> None:
        """Should raise with invalid timeouts."""
        with pytest.raises(ValueError):
            validate_timeouts(
                statement_timeout_ms=40000,  # 40s > 30s
                visibility_timeout_s=30,
            )


class TestIsTimeoutError:
    """Tests for is_timeout_error function."""

    def test_query_cancelled_is_timeout(self) -> None:
        """Should return True for QueryCanceled."""
        error = psycopg_errors.QueryCanceled()
        assert is_timeout_error(error) is True

    def test_pool_timeout_is_timeout(self) -> None:
        """Should return True for PoolTimeout."""
        error = PoolTimeout()
        assert is_timeout_error(error) is True

    def test_generic_exception_not_timeout(self) -> None:
        """Should return False for generic exceptions."""
        error = Exception("test")
        assert is_timeout_error(error) is False

    def test_value_error_not_timeout(self) -> None:
        """Should return False for ValueError."""
        error = ValueError("test")
        assert is_timeout_error(error) is False


class TestIsQueryCancelled:
    """Tests for is_query_cancelled function."""

    def test_query_cancelled(self) -> None:
        """Should return True for QueryCanceled."""
        error = psycopg_errors.QueryCanceled()
        assert is_query_cancelled(error) is True

    def test_pool_timeout_not_query_cancelled(self) -> None:
        """Should return False for PoolTimeout."""
        error = PoolTimeout()
        assert is_query_cancelled(error) is False

    def test_generic_exception_not_query_cancelled(self) -> None:
        """Should return False for generic exceptions."""
        error = Exception("test")
        assert is_query_cancelled(error) is False


class TestIsPoolTimeout:
    """Tests for is_pool_timeout function."""

    def test_pool_timeout(self) -> None:
        """Should return True for PoolTimeout."""
        error = PoolTimeout()
        assert is_pool_timeout(error) is True

    def test_query_cancelled_not_pool_timeout(self) -> None:
        """Should return False for QueryCanceled."""
        error = psycopg_errors.QueryCanceled()
        assert is_pool_timeout(error) is False

    def test_generic_exception_not_pool_timeout(self) -> None:
        """Should return False for generic exceptions."""
        error = Exception("test")
        assert is_pool_timeout(error) is False
