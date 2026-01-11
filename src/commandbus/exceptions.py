"""Command Bus exceptions."""

from typing import Any


class CommandBusError(Exception):
    """Base exception for all Command Bus errors."""


class HandlerAlreadyRegisteredError(CommandBusError):
    """Raised when attempting to register a handler for an already registered command type."""

    def __init__(self, domain: str, command_type: str) -> None:
        self.domain = domain
        self.command_type = command_type
        super().__init__(f"Handler already registered for {domain}.{command_type}")


class HandlerNotFoundError(CommandBusError):
    """Raised when no handler is registered for a command type."""

    def __init__(self, domain: str, command_type: str) -> None:
        self.domain = domain
        self.command_type = command_type
        super().__init__(f"No handler registered for {domain}.{command_type}")


class DuplicateCommandError(CommandBusError):
    """Raised when attempting to send a command with a duplicate command_id."""

    def __init__(self, domain: str, command_id: str) -> None:
        self.domain = domain
        self.command_id = command_id
        super().__init__(f"Duplicate command_id {command_id} in domain {domain}")


class TransientCommandError(CommandBusError):
    """Raised for retryable failures (network, timeout, temporary unavailability)."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.error_message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


class PermanentCommandError(CommandBusError):
    """Raised for non-retryable failures (validation, business rule violations)."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.error_message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


class BusinessRuleException(CommandBusError):
    """Raised for business rule violations that should fail immediately.

    Unlike TransientCommandError (retries, then TSQ) or PermanentCommandError (TSQ),
    BusinessRuleException:
    - Bypasses the Troubleshooting Queue entirely
    - Sets command status directly to FAILED
    - Triggers immediate compensation for process-managed commands
    - Does not require operator intervention

    Use this for deterministic business rule violations where:
    - Retrying won't help (the failure is inherent to the request)
    - Operator intervention isn't needed (the appropriate action is predetermined)
    - The system should automatically recover via compensation

    Examples:
    - Account closed before statement generation
    - Invalid date range in report request
    - Missing required data that won't appear later
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.error_message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


class CommandNotFoundError(CommandBusError):
    """Raised when a command does not exist."""

    def __init__(self, domain: str, command_id: str) -> None:
        self.domain = domain
        self.command_id = command_id
        super().__init__(f"Command {command_id} not found in domain {domain}")


class InvalidOperationError(CommandBusError):
    """Raised when an operation is invalid for the current command state."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class BatchNotFoundError(CommandBusError):
    """Raised when a batch does not exist."""

    def __init__(self, domain: str, batch_id: str) -> None:
        self.domain = domain
        self.batch_id = batch_id
        super().__init__(f"Batch {batch_id} not found in domain {domain}")
