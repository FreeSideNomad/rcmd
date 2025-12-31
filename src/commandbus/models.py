"""Command Bus domain models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol
from uuid import UUID


class CommandStatus(str, Enum):
    """Status of a command in its lifecycle."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    IN_TROUBLESHOOTING_QUEUE = "IN_TROUBLESHOOTING_QUEUE"


class ReplyOutcome(str, Enum):
    """Outcome of command processing."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


@dataclass(frozen=True)
class Command:
    """A command to be processed by a handler.

    Attributes:
        domain: The domain this command belongs to (e.g., "payments")
        command_type: The type of command (e.g., "DebitAccount")
        command_id: Unique identifier for this command
        data: The command payload
        correlation_id: ID for tracing related commands
        reply_to: Queue to send reply to
        created_at: When the command was created
    """

    domain: str
    command_type: str
    command_id: UUID
    data: dict[str, Any]
    correlation_id: UUID | None = None
    reply_to: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class VisibilityExtender(Protocol):
    """Protocol for extending visibility timeout."""

    async def extend(self, seconds: int) -> None:
        """Extend the visibility timeout by the specified seconds."""
        ...


@dataclass
class HandlerContext:
    """Context provided to command handlers.

    Provides access to command metadata and utilities like
    visibility timeout extension for long-running handlers.

    Attributes:
        command: The command being processed
        attempt: Current attempt number (1-based)
        max_attempts: Maximum attempts before exhaustion
        msg_id: PGMQ message ID
        visibility_extender: Utility to extend visibility timeout
    """

    command: Command
    attempt: int
    max_attempts: int
    msg_id: int
    visibility_extender: VisibilityExtender | None = None

    async def extend_visibility(self, seconds: int) -> None:
        """Extend the visibility timeout for long-running operations.

        Args:
            seconds: Additional seconds to extend visibility

        Raises:
            RuntimeError: If visibility extender is not available
        """
        if self.visibility_extender is None:
            raise RuntimeError("Visibility extender not available")
        await self.visibility_extender.extend(seconds)


@dataclass
class CommandMetadata:
    """Metadata stored for each command.

    Attributes:
        domain: The domain this command belongs to
        command_id: Unique identifier
        command_type: Type of command
        status: Current status
        attempts: Number of processing attempts
        max_attempts: Maximum allowed attempts
        msg_id: Current PGMQ message ID
        correlation_id: Correlation ID for tracing
        reply_to: Reply queue
        last_error_type: Type of last error (TRANSIENT/PERMANENT)
        last_error_code: Application error code
        last_error_msg: Error message
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    domain: str
    command_id: UUID
    command_type: str
    status: CommandStatus
    attempts: int = 0
    max_attempts: int = 3
    msg_id: int | None = None
    correlation_id: UUID | None = None
    reply_to: str | None = None
    last_error_type: str | None = None
    last_error_code: str | None = None
    last_error_msg: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class Reply:
    """Reply message sent after command processing.

    Attributes:
        command_id: ID of the command this is a reply to
        correlation_id: Correlation ID from the command
        outcome: Result of processing (SUCCESS, FAILED, CANCELED)
        data: Optional result data
        error_code: Error code if failed
        error_message: Error message if failed
    """

    command_id: UUID
    correlation_id: UUID | None
    outcome: ReplyOutcome
    data: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class TroubleshootingItem:
    """A command in the troubleshooting queue awaiting operator action.

    Attributes:
        domain: The domain this command belongs to
        command_id: Unique identifier
        command_type: Type of command
        attempts: Number of processing attempts made
        max_attempts: Maximum allowed attempts
        last_error_type: Type of last error (TRANSIENT/PERMANENT)
        last_error_code: Application error code
        last_error_msg: Error message
        correlation_id: Correlation ID for tracing
        reply_to: Reply queue
        payload: Original command payload from PGMQ archive
        created_at: When the command was created
        updated_at: When the command was last updated
    """

    domain: str
    command_id: UUID
    command_type: str
    attempts: int
    max_attempts: int
    last_error_type: str | None
    last_error_code: str | None
    last_error_msg: str | None
    correlation_id: UUID | None
    reply_to: str | None
    payload: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
