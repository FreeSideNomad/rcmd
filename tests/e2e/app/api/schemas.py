"""Pydantic schema definitions for E2E API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# =============================================================================
# Command Schemas
# =============================================================================


class CommandBehavior(BaseModel):
    """Probabilistic test command behavior specification.

    Commands are evaluated sequentially:
    1. Roll for fail_permanent_pct -> PermanentCommandError
    2. Roll for fail_transient_pct -> TransientCommandError
    3. Roll for timeout_pct -> Sleep > visibility_timeout
    4. Otherwise -> Success with duration from normal distribution
    """

    fail_permanent_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Probability (0-100) of permanent failure",
    )
    fail_transient_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Probability (0-100) of transient failure",
    )
    timeout_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Probability (0-100) of timeout",
    )
    min_duration_ms: int = Field(
        default=0,
        ge=0,
        description="Minimum execution duration in ms for success",
    )
    max_duration_ms: int = Field(
        default=0,
        ge=0,
        description="Maximum execution duration in ms for success",
    )
    error_code: str | None = Field(default=None, description="Error code for failures")
    error_message: str | None = Field(default=None, description="Error message for failures")
    send_response: bool = Field(
        default=False,
        description="If true, handler returns response data to reply queue",
    )
    response_data: dict[str, Any] | None = Field(
        default=None,
        description="Custom data to include in reply (when send_response=true)",
    )


class CreateCommandRequest(BaseModel):
    """Request to create a test command."""

    behavior: CommandBehavior = Field(default_factory=CommandBehavior)
    payload: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)
    reply_to: str | None = Field(
        default=None,
        description="Queue name to send reply to (e.g., 'e2e__replies')",
    )


class CreateCommandResponse(BaseModel):
    """Response after creating a command."""

    command_id: UUID
    status: str = "PENDING"
    behavior: CommandBehavior
    payload: dict[str, Any]
    reply_to: str | None = None
    message: str


class BulkCreateRequest(BaseModel):
    """Request to create multiple test commands with probabilistic behavior."""

    count: int = Field(default=1, ge=1, le=1000000)
    behavior: CommandBehavior = Field(default_factory=CommandBehavior)
    max_attempts: int = Field(default=3, ge=1, le=10)


class BulkCreateResponse(BaseModel):
    """Response after creating bulk commands."""

    created: int
    command_ids: list[str]
    total_command_ids: int
    generation_time_ms: int
    queue_time_ms: int
    message: str


class CommandResponse(BaseModel):
    """Single command details."""

    command_id: UUID
    domain: str
    command_type: str
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime | None
    updated_at: datetime | None
    correlation_id: UUID | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    payload: dict[str, Any] | None = None


class CommandListResponse(BaseModel):
    """Paginated list of commands."""

    commands: list[CommandResponse]
    total: int
    limit: int
    offset: int


# =============================================================================
# Stats Schemas
# =============================================================================


class ProcessingRate(BaseModel):
    """Processing rate metrics."""

    per_minute: int
    avg_time_ms: int
    p50_ms: int
    p95_ms: int
    p99_ms: int


class StatsOverviewResponse(BaseModel):
    """Dashboard overview statistics."""

    status_counts: dict[str, int]
    processing_rate: ProcessingRate
    recent_change: dict[str, int]
    error: str | None = None


class ActivityEvent(BaseModel):
    """Recent activity event."""

    command_id: str
    event_type: str
    timestamp: str | None
    summary: str


class RecentActivityResponse(BaseModel):
    """Recent activity feed."""

    events: list[ActivityEvent]
    error: str | None = None


class ThroughputResponse(BaseModel):
    """Processing throughput metrics."""

    window_seconds: int
    commands_processed: int
    throughput_per_second: float
    avg_processing_time_ms: int
    p50_ms: int
    p95_ms: int
    p99_ms: int
    active_workers: int
    queue_depth: int
    error: str | None = None


class LoadTestResponse(BaseModel):
    """Load test progress."""

    total_commands: int
    completed: int
    failed: int
    in_tsq: int
    pending: int
    progress_percent: float
    elapsed_seconds: int
    estimated_remaining_seconds: int
    throughput_per_second: float
    error: str | None = None


# =============================================================================
# TSQ Schemas
# =============================================================================


class TSQCommandResponse(BaseModel):
    """TSQ command details."""

    command_id: str
    domain: str
    command_type: str
    status: str
    attempts: int
    max_attempts: int
    last_error_type: str | None
    last_error_code: str | None
    last_error_message: str | None
    created_at: str | None
    updated_at: str | None


class TSQListResponse(BaseModel):
    """Paginated list of TSQ commands."""

    commands: list[TSQCommandResponse]
    total: int
    limit: int
    offset: int
    all_command_ids: list[str] = []  # All command IDs for "select all" feature
    error: str | None = None


class TSQOperatorRequest(BaseModel):
    """Request for TSQ operator actions."""

    operator: str = "e2e-ui"
    reason: str | None = None
    result_data: dict[str, Any] | None = None


class TSQActionResponse(BaseModel):
    """Response for TSQ actions."""

    command_id: str
    status: str
    message: str
    result_data: dict[str, Any] | None = None
    operator: str | None = None
    error: str | None = None


class TSQBulkRetryRequest(BaseModel):
    """Request to bulk retry TSQ commands."""

    command_ids: list[str]
    operator: str = "e2e-ui"


class TSQBulkRetryResponse(BaseModel):
    """Response for bulk TSQ retry."""

    retried: int
    command_ids: list[str]
    message: str
    error: str | None = None


# =============================================================================
# Audit Schemas
# =============================================================================


class AuditEvent(BaseModel):
    """Single audit event."""

    id: int
    event_type: str
    timestamp: str | None
    details: dict[str, Any]


class AuditTrailResponse(BaseModel):
    """Audit trail for a command."""

    command_id: str
    events: list[AuditEvent]
    total_duration_ms: int
    error: str | None = None


class AuditSearchEvent(BaseModel):
    """Audit event from search results."""

    id: int
    command_id: str
    event_type: str
    timestamp: str | None
    details: dict[str, Any]
    domain: str
    command_type: str


class AuditSearchResponse(BaseModel):
    """Paginated audit search results."""

    events: list[AuditSearchEvent]
    total: int
    limit: int
    offset: int
    error: str | None = None


# =============================================================================
# Batch Schemas
# =============================================================================


class CreateBatchRequest(BaseModel):
    """Request to create a batch of test commands."""

    name: str = Field(default="Test Batch", description="Batch name")
    command_count: int = Field(default=10, ge=1, le=10000)
    behavior: CommandBehavior = Field(default_factory=CommandBehavior)
    max_attempts: int = Field(default=3, ge=1, le=10)


class CreateBatchResponse(BaseModel):
    """Response after creating a batch."""

    batch_id: UUID
    total_commands: int
    message: str


class BatchSummary(BaseModel):
    """Batch summary for list view."""

    batch_id: UUID
    name: str | None
    status: str
    total_count: int
    completed_count: int
    failed_count: int
    canceled_count: int
    in_troubleshooting_count: int
    progress_percent: float
    created_at: datetime | None


class BatchListResponse(BaseModel):
    """Paginated list of batches."""

    batches: list[BatchSummary]
    total: int
    limit: int
    offset: int
    error: str | None = None


class BatchDetailResponse(BaseModel):
    """Batch detail with full info."""

    batch_id: UUID
    name: str | None
    status: str
    total_count: int
    completed_count: int
    failed_count: int
    canceled_count: int
    in_troubleshooting_count: int
    progress_percent: float
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    custom_data: dict[str, Any] | None = None
    error: str | None = None


class BatchCommandResponse(BaseModel):
    """Command in a batch."""

    command_id: UUID
    command_type: str
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime | None
    last_error_code: str | None = None
    last_error_message: str | None = None


class BatchCommandsListResponse(BaseModel):
    """Paginated list of commands in a batch."""

    commands: list[BatchCommandResponse]
    total: int
    limit: int
    offset: int
    error: str | None = None


# =============================================================================
# Config Schemas
# =============================================================================


class WorkerConfigSchema(BaseModel):
    """Worker configuration."""

    visibility_timeout: int = 30
    concurrency: int = 4
    poll_interval: float = 1.0
    batch_size: int = 10


class RetryConfigSchema(BaseModel):
    """Retry configuration."""

    max_attempts: int = 3
    backoff_schedule: list[int] = [10, 60, 300]


class ConfigResponse(BaseModel):
    """Configuration response."""

    worker: WorkerConfigSchema
    retry: RetryConfigSchema
    error: str | None = None


class ConfigUpdateRequest(BaseModel):
    """Configuration update request."""

    worker: WorkerConfigSchema | None = None
    retry: RetryConfigSchema | None = None


class ConfigUpdateResponse(BaseModel):
    """Configuration update response."""

    status: str
    config: ConfigUpdateRequest | None = None
    error: str | None = None


# =============================================================================
# Health Schemas
# =============================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    database: str
    error: str | None = None


# =============================================================================
# Reply Queue Schemas
# =============================================================================


class ReplyMessage(BaseModel):
    """A reply message from the reply queue."""

    msg_id: int
    command_id: str
    correlation_id: str | None = None
    outcome: str
    result: dict[str, Any] | None = None
    enqueued_at: str | None = None


class ReplyQueueResponse(BaseModel):
    """List of reply messages."""

    messages: list[ReplyMessage]
    queue_name: str
    queue_depth: int
    error: str | None = None


class ReplySummaryResponse(BaseModel):
    """Reply aggregation summary for a batch."""

    id: int
    batch_id: UUID
    domain: str
    total_expected: int
    success_count: int
    failed_count: int
    canceled_count: int
    total_received: int
    is_complete: bool
    created_at: datetime | None
    completed_at: datetime | None


class ReplySummaryListResponse(BaseModel):
    """List of reply summaries."""

    summaries: list[ReplySummaryResponse]
    total: int
    limit: int
    offset: int
    error: str | None = None
