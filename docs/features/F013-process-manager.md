# F013: Process Manager

## Summary

Enable orchestration of multi-step command flows with stateful coordination, reply-driven progression, and full audit trails.

## Motivation

Applications often need to coordinate multiple commands in a sequence where each step depends on the outcome of previous steps:
- Workflow orchestration (query -> aggregate -> render)
- Multi-step transactions with compensation on failure
- Long-running processes that span multiple command executions

Without process management, applications must implement their own:
- State tracking across command boundaries
- Reply correlation and routing
- Audit logging for debugging
- Failure handling and compensation

## User Stories

- [S057](stories/S057-process-models.md) - Process Manager domain models
- [S058](stories/S058-process-repository.md) - Process persistence layer
- [S059](stories/S059-base-process-manager.md) - Base ProcessManager implementation
- [S060](stories/S060-process-reply-router.md) - Reply router for process queues
- [S061](stories/S061-process-audit-trail.md) - Process audit trail logging
- [S062](stories/S062-process-failure-handling.md) - Process failure and TSQ integration
- [S063](stories/S063-e2e-statement-report-process.md) - E2E StatementReportProcess handlers
- [S064](stories/S064-e2e-process-batch-ui.md) - E2E UI for process batch initiation
- [S065](stories/S065-e2e-process-list-ui.md) - E2E UI for viewing processes
- [S066](stories/S066-e2e-process-detail-ui.md) - E2E UI for process details and audit

## Acceptance Criteria (Feature-Level)

- [ ] Process metadata stored in `commandbus.process` table
- [ ] Process audit entries stored in `commandbus.process_audit` table
- [ ] Processes can be started with typed initial state
- [ ] Commands sent with `correlation_id=process_id` for reply routing
- [ ] Reply router dispatches replies to appropriate process managers
- [ ] Process status transitions: PENDING -> IN_PROGRESS -> WAITING -> COMPLETED/FAILED
- [ ] Failed commands in TSQ set process to WAITING_FOR_TSQ
- [ ] TSQ cancellation triggers compensation flow
- [ ] Full audit trail of commands and replies per process
- [ ] E2E scenario demonstrates StatementReportProcess batch execution

## Technical Design

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Application                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │               Process Manager Registry                     │  │
│  │  StatementReportProcess, ... (keyed by process_type)       │  │
│  └──────────────────────────┬────────────────────────────────┘  │
│                             │                                    │
│  ┌──────────────────────────┴─────────────────────────────────┐ │
│  │                 ProcessReplyRouter                         │ │
│  │  - Consumes process reply queue                            │ │
│  │  - Looks up process by correlation_id                      │ │
│  │  - Dispatches to appropriate ProcessManager.handle_reply() │ │
│  └──────────────────────────┬─────────────────────────────────┘ │
└─────────────────────────────┼───────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │   Process Reply Queue         │
              │   (domain__process_replies)   │
              └───────────────┬───────────────┘
                              │
       ┌──────────────────────┴──────────────────────┐
       │         Reply (correlation_id=process_id)   │
       └──────────────────────┬──────────────────────┘
                              │
┌─────────────────────────────┴───────────────────────────────────┐
│                    Command Bus Workers                          │
│  Process commands and send replies to reply_to queue            │
└─────────────────────────────────────────────────────────────────┘
```

### Process Lifecycle

```
                ┌─────────┐
                │ PENDING │
                └────┬────┘
                     │ start() called
                     ▼
              ┌────────────┐
              │ IN_PROGRESS│
              └──────┬─────┘
                     │ command sent
                     ▼
              ┌─────────────────┐
              │WAITING_FOR_REPLY│◄────────────────┐
              └────────┬────────┘                 │
                       │ reply received           │
           ┌───────────┼───────────┐              │
           ▼           ▼           ▼              │
      ┌────────┐  ┌────────┐  ┌───────────────┐   │
      │SUCCESS │  │FAILED  │  │ TSQ (command) │   │
      └───┬────┘  └────┬───┘  └───────┬───────┘   │
          │            │              │           │
          │            ▼              ▼           │
          │      ┌─────────┐  ┌──────────────┐    │
          │      │ FAILED  │  │WAITING_FOR_TSQ│   │
          │      └─────────┘  └───────┬──────┘    │
          │                          │            │
          │           ┌──────────────┼──────────┐ │
          │           ▼              ▼          │ │
          │    ┌───────────┐  ┌───────────────┐│ │
          │    │TSQ Cancel │  │ TSQ Complete  ││ │
          │    └─────┬─────┘  └───────┬───────┘│ │
          │          │                │        │ │
          │          ▼                └────────┘ │
          │   ┌─────────────┐                    │
          │   │COMPENSATING │                    │
          │   └──────┬──────┘                    │
          │          │                           │
          │          ▼                           │
          │   ┌─────────────┐    has next step   │
          │   │COMPENSATED  │    ─────────────────┘
          │   └─────────────┘
          │
          │ get_next_step() returns None
          ▼
    ┌───────────┐
    │ COMPLETED │
    └───────────┘
```

### Dependencies

- F001: Command Sending (for sending process commands)
- F002: Command Processing (for command handling)
- F004: Troubleshooting Queue (for TSQ integration)
- F009: Batch Commands (for batch process initiation)
- F010: Database Schema Management (for migrations)

### Data Changes

#### New Table: `commandbus.process`

```sql
CREATE TABLE commandbus.process (
    domain VARCHAR(255) NOT NULL,
    process_id UUID NOT NULL,
    process_type VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    current_step VARCHAR(255),
    state JSONB NOT NULL DEFAULT '{}',
    error_code VARCHAR(255),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (domain, process_id)
);

CREATE INDEX idx_process_type ON commandbus.process(domain, process_type);
CREATE INDEX idx_process_status ON commandbus.process(domain, status);
CREATE INDEX idx_process_created ON commandbus.process(created_at);
```

#### New Table: `commandbus.process_audit`

```sql
CREATE TABLE commandbus.process_audit (
    id BIGSERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    process_id UUID NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    command_id UUID NOT NULL,
    command_type VARCHAR(255) NOT NULL,
    command_data JSONB,
    sent_at TIMESTAMPTZ NOT NULL,
    reply_outcome VARCHAR(50),
    reply_data JSONB,
    received_at TIMESTAMPTZ,
    FOREIGN KEY (domain, process_id) REFERENCES commandbus.process(domain, process_id)
);

CREATE INDEX idx_process_audit_process ON commandbus.process_audit(domain, process_id);
CREATE INDEX idx_process_audit_command ON commandbus.process_audit(command_id);
```

### API Changes

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, StrEnum
from typing import Any, Generic, Protocol, Self, TypeVar
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
    """Protocol for typed process state."""

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
    status: ProcessStatus
    current_step: TStep | None
    state: TState
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None


@dataclass
class ProcessAuditEntry:
    """Audit trail entry for process step execution."""
    step_name: str
    command_id: UUID
    command_type: str
    command_data: dict[str, Any] | None
    sent_at: datetime
    reply_outcome: ReplyOutcome | None
    reply_data: dict[str, Any] | None
    received_at: datetime | None


class BaseProcessManager(ABC, Generic[TState, TStep]):
    """Base class for implementing process managers."""

    @property
    @abstractmethod
    def process_type(self) -> str:
        """Return unique process type identifier."""
        pass

    @property
    @abstractmethod
    def domain(self) -> str:
        """Return the domain this process operates in."""
        pass

    async def start(self, initial_data: dict[str, Any]) -> UUID:
        """Start a new process instance."""
        ...

    @abstractmethod
    def create_initial_state(self, initial_data: dict[str, Any]) -> TState:
        """Create typed state from initial input data."""
        pass

    @abstractmethod
    def get_first_step(self, state: TState) -> TStep:
        """Determine the first step based on initial state."""
        pass

    @abstractmethod
    async def build_command(self, step: TStep, state: TState) -> "ProcessCommand[Any]":
        """Build typed command for a step."""
        pass

    @abstractmethod
    def update_state(self, state: TState, step: TStep, reply: Reply) -> None:
        """Update state in place with data from reply."""
        pass

    @abstractmethod
    def get_next_step(
        self, current_step: TStep, reply: Reply, state: TState
    ) -> TStep | None:
        """Determine next step. Returns None when process is complete."""
        pass

    async def handle_reply(
        self, reply: Reply, process: ProcessMetadata[TState, TStep]
    ) -> None:
        """Handle incoming reply and advance process."""
        ...


class ProcessReplyRouter:
    """Routes replies from process queue to appropriate process managers."""

    def __init__(
        self,
        pool,
        process_repo: "ProcessRepository",
        managers: dict[str, BaseProcessManager],
        reply_queue: str,
    ):
        ...

    async def run(self, poll_interval: float = 1.0) -> None:
        """Run reply router continuously."""
        ...
```

## Out of Scope

- Process timeout handling (future enhancement)
- Process persistence across application restarts (recovery logic)
- Parallel step execution within a process
- Conditional branching between steps (handled in get_next_step)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Reply ordering issues | Medium | correlation_id ensures replies reach correct process |
| Process stuck in WAITING | Medium | Monitoring + manual intervention via process queries |
| Compensation failure | High | Log compensation failures, manual recovery |
| Large state JSON | Low | Document size limits, recommend external storage for large data |

## Implementation Milestones

- [ ] Milestone 1: Database schema (process, process_audit tables)
- [ ] Milestone 2: Domain models (ProcessMetadata, ProcessStatus, ProcessAuditEntry)
- [ ] Milestone 3: Process repository (save, update, get_by_id, audit logging)
- [ ] Milestone 4: BaseProcessManager abstract class
- [ ] Milestone 5: ProcessReplyRouter implementation
- [ ] Milestone 6: E2E StatementReportProcess handlers
- [ ] Milestone 7: E2E UI for process batch initiation
- [ ] Milestone 8: E2E UI for process list and details

## LLM Agent Notes

**Reference Files:**
- `docs/process-manager-design.md` - Full design specification
- `src/commandbus/models.py` - Existing command bus models
- `src/commandbus/repositories/postgres.py` - Repository patterns
- `tests/e2e/app/` - E2E application structure
- `tests/e2e/app/web/routes.py` - Web routes for UI
- `tests/e2e/app/api/routes.py` - API routes

**Patterns to Follow:**
- Repository pattern from `src/commandbus/repositories/`
- E2E UI patterns from existing pages (commands, batches)
- Handler registration from `tests/e2e/app/handlers/`
- Probabilistic behavior from F011

**Constraints:**
- Process commands use `correlation_id=process_id`
- Reply routing via dedicated reply queue per domain
- State serialization via `to_dict()`/`from_dict()` methods
- Step names as StrEnum values

**Verification Steps:**
1. `make test-unit` - Unit tests pass
2. `make test-integration` - Integration tests pass
3. `make typecheck` - No type errors
4. Start process, verify state transitions, check audit trail
