"""Retry policies for command processing."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RetryPolicy:
    """Policy for handling command retries.

    Attributes:
        max_attempts: Maximum number of attempts before giving up
        backoff_schedule: List of visibility timeouts in seconds for each retry.
                         Index 0 is used for attempt 2, index 1 for attempt 3, etc.
                         If attempts exceed the schedule length, the last value is used.

    Example:
        policy = RetryPolicy(max_attempts=4, backoff_schedule=[10, 60, 300])
        # Attempt 1: immediate (initial processing)
        # Attempt 2: 10 seconds delay
        # Attempt 3: 60 seconds delay
        # Attempt 4: 300 seconds delay
    """

    max_attempts: int = 3
    backoff_schedule: list[int] = field(default_factory=lambda: [10, 60, 300])

    def get_backoff(self, attempt: int) -> int:
        """Get the backoff delay for a given attempt number.

        Args:
            attempt: The current attempt number (1-based)

        Returns:
            Visibility timeout in seconds for the next retry.
            Returns 0 if no more retries should occur.
        """
        if attempt >= self.max_attempts:
            return 0  # No more retries

        # Attempt 1 -> index 0, attempt 2 -> index 1, etc.
        index = attempt - 1
        if index < 0:
            return self.backoff_schedule[0] if self.backoff_schedule else 30

        if index < len(self.backoff_schedule):
            return self.backoff_schedule[index]

        # Use last value for attempts beyond schedule length
        return self.backoff_schedule[-1] if self.backoff_schedule else 30

    def should_retry(self, attempt: int) -> bool:
        """Check if another retry should be attempted.

        Args:
            attempt: The current attempt number (1-based)

        Returns:
            True if more attempts are allowed
        """
        return attempt < self.max_attempts


# Default retry policy used by workers
DEFAULT_RETRY_POLICY = RetryPolicy()
