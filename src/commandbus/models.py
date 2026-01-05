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


class BatchStatus(str, Enum):
    """Status of a batch in its lifecycle."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_FAILURES = "COMPLETED_WITH_FAILURES"


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

    Handlers should manage their own database transactions if needed.
    Command completion happens in a separate transaction after the
    handler returns successfully.

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
        batch_id: Optional batch this command belongs to
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
    batch_id: UUID | None = None


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


@dataclass(frozen=True)
class AuditEvent:
    """An audit event in a command's lifecycle.

    Attributes:
        audit_id: Unique identifier for this audit event
        domain: The domain of the command
        command_id: The command ID
        event_type: Type of event (SENT, RECEIVED, FAILED, etc.)
        timestamp: When the event occurred
        details: Optional additional details (error info, etc.)
    """

    audit_id: int
    domain: str
    command_id: UUID
    event_type: str
    timestamp: datetime
    details: dict[str, Any] | None = None


@dataclass
class SendRequest:
    """Request to send a single command (used in batch operations).

    Attributes:
        domain: The domain to send to (e.g., "payments")
        command_type: The type of command (e.g., "DebitAccount")
        command_id: Unique identifier for this command
        data: The command payload
        correlation_id: Optional correlation ID for tracing
        reply_to: Optional reply queue name
        max_attempts: Max retry attempts (defaults to bus default)
    """

    domain: str
    command_type: str
    command_id: UUID
    data: dict[str, Any]
    correlation_id: UUID | None = None
    reply_to: str | None = None
    max_attempts: int | None = None


@dataclass
class SendResult:
    """Result of sending a command.

    Attributes:
        command_id: The unique ID of the sent command
        msg_id: The PGMQ message ID assigned
    """

    command_id: UUID
    msg_id: int


@dataclass
class BatchSendResult:
    """Result of a batch send operation.

    Attributes:
        results: Individual results for each command sent
        chunks_processed: Number of transaction chunks processed
        total_commands: Total number of commands sent
    """

    results: list[SendResult]
    chunks_processed: int
    total_commands: int


@dataclass(frozen=True)
class BatchCommand:
    """A command to be included in a batch.

    Attributes:
        command_type: The type of command (e.g., "DebitAccount")
        command_id: Unique identifier for this command
        data: The command payload
        correlation_id: Optional correlation ID for tracing
        reply_to: Optional reply queue name
        max_attempts: Max retry attempts (defaults to bus default)
    """

    command_type: str
    command_id: UUID
    data: dict[str, Any]
    correlation_id: UUID | None = None
    reply_to: str | None = None
    max_attempts: int | None = None


@dataclass
class BatchMetadata:
    """Metadata stored for a batch of commands.

    Attributes:
        domain: The domain this batch belongs to
        batch_id: Unique identifier
        name: Optional human-readable name for the batch
        custom_data: Optional custom metadata
        status: Current batch status
        total_count: Total number of commands in the batch
        completed_count: Number of successfully completed commands
        canceled_count: Number of canceled commands (after TSQ resolution)
        in_troubleshooting_count: Number of commands currently in TSQ
        created_at: Batch creation timestamp
        started_at: When first command was processed
        completed_at: When all commands reached terminal state
    """

    domain: str
    batch_id: UUID
    status: BatchStatus = BatchStatus.PENDING
    name: str | None = None
    custom_data: dict[str, Any] | None = None
    total_count: int = 0
    completed_count: int = 0
    canceled_count: int = 0
    in_troubleshooting_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class CreateBatchResult:
    """Result of creating a batch with commands.

    Attributes:
        batch_id: The unique ID of the created batch
        command_results: Individual results for each command sent
        total_commands: Total number of commands in the batch
    """

    batch_id: UUID
    command_results: list[SendResult]
    total_commands: int
