"""Unit tests for retry policies."""

from commandbus.policies import DEFAULT_RETRY_POLICY, RetryPolicy


class TestRetryPolicy:
    """Tests for RetryPolicy."""

    def test_default_policy_values(self) -> None:
        """Test default policy has expected values."""
        policy = RetryPolicy()
        assert policy.max_attempts == 3
        assert policy.backoff_schedule == [10, 60, 300]

    def test_custom_policy_values(self) -> None:
        """Test custom policy values."""
        policy = RetryPolicy(max_attempts=5, backoff_schedule=[5, 15, 45, 120])
        assert policy.max_attempts == 5
        assert policy.backoff_schedule == [5, 15, 45, 120]

    def test_should_retry_within_max_attempts(self) -> None:
        """Test should_retry returns True when under max attempts."""
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(1) is True
        assert policy.should_retry(2) is True

    def test_should_retry_at_max_attempts(self) -> None:
        """Test should_retry returns False at max attempts."""
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(3) is False

    def test_should_retry_over_max_attempts(self) -> None:
        """Test should_retry returns False over max attempts."""
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(4) is False

    def test_get_backoff_for_attempt_1(self) -> None:
        """Test backoff for first attempt uses first schedule value."""
        policy = RetryPolicy(max_attempts=4, backoff_schedule=[10, 60, 300])
        assert policy.get_backoff(1) == 10

    def test_get_backoff_for_attempt_2(self) -> None:
        """Test backoff for second attempt uses second schedule value."""
        policy = RetryPolicy(max_attempts=4, backoff_schedule=[10, 60, 300])
        assert policy.get_backoff(2) == 60

    def test_get_backoff_for_attempt_3(self) -> None:
        """Test backoff for third attempt uses third schedule value."""
        policy = RetryPolicy(max_attempts=4, backoff_schedule=[10, 60, 300])
        assert policy.get_backoff(3) == 300

    def test_get_backoff_beyond_schedule_uses_last(self) -> None:
        """Test backoff beyond schedule length uses last value."""
        policy = RetryPolicy(max_attempts=10, backoff_schedule=[10, 60, 300])
        # Attempt 4 and beyond should use 300 (last value)
        assert policy.get_backoff(4) == 300
        assert policy.get_backoff(5) == 300

    def test_get_backoff_at_max_attempts_returns_zero(self) -> None:
        """Test backoff at max attempts returns 0."""
        policy = RetryPolicy(max_attempts=3, backoff_schedule=[10, 60, 300])
        assert policy.get_backoff(3) == 0

    def test_get_backoff_over_max_attempts_returns_zero(self) -> None:
        """Test backoff over max attempts returns 0."""
        policy = RetryPolicy(max_attempts=3, backoff_schedule=[10, 60, 300])
        assert policy.get_backoff(4) == 0

    def test_empty_backoff_schedule(self) -> None:
        """Test handling empty backoff schedule."""
        policy = RetryPolicy(max_attempts=3, backoff_schedule=[])
        # Should return default 30
        assert policy.get_backoff(1) == 30

    def test_default_retry_policy_constant(self) -> None:
        """Test DEFAULT_RETRY_POLICY is properly configured."""
        assert DEFAULT_RETRY_POLICY.max_attempts == 3
        assert DEFAULT_RETRY_POLICY.backoff_schedule == [10, 60, 300]


class TestBackoffScheduleScenarios:
    """Test backoff schedule scenarios from acceptance criteria."""

    def test_backoff_schedule_scenario(self) -> None:
        """Test the acceptance criteria scenario.

        Given backoff schedule is [10, 60, 300]
        When the retry policy is applied
        Then attempt 2 has VT of 10 seconds
        And attempt 3 has VT of 60 seconds
        And attempt 4 would have VT of 300 seconds
        """
        policy = RetryPolicy(max_attempts=4, backoff_schedule=[10, 60, 300])

        # Attempt 1 -> backoff for retry (index 0)
        assert policy.get_backoff(1) == 10

        # Attempt 2 -> backoff for retry (index 1)
        assert policy.get_backoff(2) == 60

        # Attempt 3 -> backoff for retry (index 2)
        assert policy.get_backoff(3) == 300
