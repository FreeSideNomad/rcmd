"""Process Manager domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any, Generic, Protocol, Self, TypeVar

if TYPE_CHECKING:
    from uuid import UUID

    from commandbus.models import Reply, ReplyOutcome


class ProcessStatus(str, Enum):
    """Status of a process instance."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_FOR_REPLY = "WAITING"
    WAITING_FOR_TSQ = "WAITING_FOR_TSQ"
    COMPENSATING = "COMPENSATING"
    COMPLETED = "COMPLETED"
    COMPENSATED = "COMPENSATED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class ProcessState(Protocol):
    """Protocol for typed process state.

    Process state classes must implement to_dict() and from_dict() for
    JSON serialization to/from database storage.
    """

    def to_dict(self) -> dict[str, Any]:
        """Serialize state to JSON-compatible dict."""
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize state from JSON-compatible dict."""
        ...


TState = TypeVar("TState", bound=ProcessState)
TStep = TypeVar("TStep", bound=StrEnum)


@dataclass
class ProcessMetadata(Generic[TState, TStep]):
    """Metadata for a process instance."""

    domain: str
    process_id: UUID
    process_type: str
    state: TState
    status: ProcessStatus = ProcessStatus.PENDING
    current_step: TStep | None = None

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    # Error info
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class ProcessAuditEntry:
    """Audit trail entry for process step execution."""

    step_name: str
    command_id: UUID
    command_type: str
    command_data: dict[str, Any] | None
    sent_at: datetime
    reply_outcome: ReplyOutcome | None = None
    reply_data: dict[str, Any] | None = None
    received_at: datetime | None = None


TData = TypeVar("TData")


@dataclass(frozen=True)
class ProcessCommand(Generic[TData]):
    """Typed wrapper for process command data."""

    command_type: str
    data: TData

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "command_type": self.command_type,
            "data": self.data.to_dict() if hasattr(self.data, "to_dict") else self.data,
        }


TResult = TypeVar("TResult")


@dataclass(frozen=True)
class ProcessResponse(Generic[TResult]):
    """Typed wrapper for command response data."""

    outcome: ReplyOutcome
    result: TResult | None
    error_code: str | None
    error_message: str | None

    @classmethod
    def from_reply(
        cls,
        reply: Reply,
        result_type: type[TResult],
    ) -> ProcessResponse[TResult]:
        """Create from a Reply object."""
        result = None
        if reply.data is not None:
            if hasattr(result_type, "from_dict"):
                result = result_type.from_dict(reply.data)  # type: ignore
            else:
                result = reply.data

        return cls(
            outcome=reply.outcome,
            result=result,
            error_code=reply.error_code,
            error_message=reply.error_message,
        )
