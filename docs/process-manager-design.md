# Process Manager Design

A lightweight process orchestration pattern for coordinating multi-step command flows with the Command Bus.

## Overview

The Process Manager pattern enables orchestration of multiple commands where each step depends on the outcome of previous steps. It provides:

- **Stateful coordination** - Track process state across multiple command executions
- **Reply-driven progression** - Advance process based on command replies
- **Full audit trail** - Record all commands, replies, and state transitions
- **Typed messages** - Type-safe command requests and responses

## Core Concepts

### Process Manager

A Process Manager is a stateful coordinator that:
1. Initiates a process with a unique `process_id` (UUID)
2. Sends commands using `process_id` as `correlation_id`
3. Receives replies via a dedicated reply queue
4. Maintains process state (current step, accumulated data)
5. Determines and executes next steps based on reply outcomes

```
┌────────────────────────────────────────────────────────────────┐
│                      Process Manager                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Process ID   │  │ State JSON   │  │ Step Registry        │  │
│  │ (correlation)│  │ (accumulated │  │ (step_name → handler)│  │
│  │              │  │  data)       │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    Audit Log                             │  │
│  │  [{step, command_id, sent_at, reply, received_at}, ...]  │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

### Process Flow

```
1. START: Create process with unique process_id
      │
      ▼
2. SEND: Send command with correlation_id=process_id, reply_to=process_queue
      │
      ▼
3. WAIT: Process Manager listens on reply queue for correlation_id match
      │
      ▼
4. RECEIVE: Reply arrives with correlation_id=process_id
      │
      ▼
5. PROCESS:
   - Extract relevant data from reply
   - Update process state JSON
   - Record in audit log
   - Determine next step
      │
      ├──── Has next step? ───► Go to step 2 (SEND)
      │
      └──── Process complete? ───► 6. COMPLETE
```

## Data Model

### ProcessMetadata

```python
from typing import Generic, TypeVar

TState = TypeVar("TState", bound="ProcessState")
TStep = TypeVar("TStep", bound=StrEnum)

@dataclass
class ProcessMetadata(Generic[TState, TStep]):
    """Metadata for a process instance with typed state and steps."""
    domain: str                              # Domain this process belongs to
    process_id: UUID                         # Unique process identifier (also correlation_id)
    process_type: str                        # Type of process (e.g., "OrderFulfillment")
    status: ProcessStatus                    # PENDING, IN_PROGRESS, COMPLETED, FAILED, CANCELED
    current_step: TStep | None               # Current/last executed step (StrEnum)
    state: TState                            # Typed process state

    # Timestamps
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    # Error info (if failed)
    error_code: str | None
    error_message: str | None
```

### ProcessStatus

```python
class ProcessStatus(str, Enum):
    PENDING = "PENDING"                    # Created but not started
    IN_PROGRESS = "IN_PROGRESS"            # Actively executing steps
    WAITING_FOR_REPLY = "WAITING"          # Sent command, awaiting reply
    WAITING_FOR_TSQ = "WAITING_FOR_TSQ"    # Command in troubleshooting queue
    COMPENSATING = "COMPENSATING"          # Running compensation steps
    COMPLETED = "COMPLETED"                # All steps finished successfully
    COMPENSATED = "COMPENSATED"            # Completed after running compensations
    FAILED = "FAILED"                      # Unrecoverable failure
    CANCELED = "CANCELED"                  # Externally canceled
```

### ProcessAuditEntry

```python
@dataclass
class ProcessAuditEntry:
    """Audit trail entry for process step execution."""
    step_name: str                    # Name of the step
    command_id: UUID                  # Command sent for this step
    command_type: str                 # Type of command sent
    command_data: dict[str, Any]      # Command payload (sanitized)
    sent_at: datetime                 # When command was sent

    # Reply info (populated when received)
    reply_outcome: ReplyOutcome | None
    reply_data: dict[str, Any] | None
    received_at: datetime | None
```

## Typed Messages

For type safety and as a template for Java implementation, command requests and responses use explicit Python dataclasses with `to_dict()` and `from_dict()` methods.

### ProcessCommand

```python
from dataclasses import dataclass
from typing import Generic, TypeVar, Any

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

    @classmethod
    def from_dict(cls, data: dict[str, Any], data_type: type[TData]) -> "ProcessCommand[TData]":
        """Create from dictionary."""
        return cls(
            command_type=data["command_type"],
            data=data_type.from_dict(data["data"]) if hasattr(data_type, "from_dict") else data["data"],
        )
```

### ProcessResponse

```python
from dataclasses import dataclass
from typing import Generic, TypeVar, Any

from commandbus.models import ReplyOutcome

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
    ) -> "ProcessResponse[TResult]":
        """Create from a Reply object."""
        result = None
        if reply.data is not None and hasattr(result_type, "from_dict"):
            result = result_type.from_dict(reply.data)
        elif reply.data is not None:
            result = reply.data

        return cls(
            outcome=reply.outcome,
            result=result,
            error_code=reply.error_code,
            error_message=reply.error_message,
        )
```

### Domain-Specific Request/Response Types

Each command step defines its own request and response types with explicit serialization:

```python
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any


class OutputType(StrEnum):
    """Output format for statement report."""
    PDF = "pdf"
    HTML = "html"
    CSV = "csv"


# Request type (command data)
@dataclass(frozen=True)
class StatementQueryRequest:
    """Request data for StatementQuery command."""
    from_date: date
    to_date: date
    account_list: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "account_list": self.account_list,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatementQueryRequest":
        return cls(
            from_date=date.fromisoformat(data["from_date"]),
            to_date=date.fromisoformat(data["to_date"]),
            account_list=data["account_list"],
        )


# Response type (result data)
@dataclass(frozen=True)
class StatementQueryResponse:
    """Response data from StatementQuery command."""
    result_path: str  # S3 path to JSON query results

    def to_dict(self) -> dict[str, Any]:
        return {"result_path": self.result_path}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatementQueryResponse":
        return cls(result_path=data["result_path"])


@dataclass(frozen=True)
class StatementDataAggregationRequest:
    """Request data for StatementDataAggregation command."""
    data_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"data_path": self.data_path}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatementDataAggregationRequest":
        return cls(data_path=data["data_path"])


@dataclass(frozen=True)
class StatementDataAggregationResponse:
    """Response data from StatementDataAggregation command."""
    result_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"result_path": self.result_path}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatementDataAggregationResponse":
        return cls(result_path=data["result_path"])


@dataclass(frozen=True)
class StatementRenderRequest:
    """Request data for StatementRender command."""
    aggregated_data_path: str
    output_type: OutputType

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregated_data_path": self.aggregated_data_path,
            "output_type": self.output_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatementRenderRequest":
        return cls(
            aggregated_data_path=data["aggregated_data_path"],
            output_type=OutputType(data["output_type"]),
        )


@dataclass(frozen=True)
class StatementRenderResponse:
    """Response data from StatementRender command."""
    result_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"result_path": self.result_path}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatementRenderResponse":
        return cls(result_path=data["result_path"])
```

### Usage in Process Manager

The `build_command` method returns a `ProcessCommand`:

```python
async def build_command(
    self,
    step: StatementReportStep,
    state: StatementReportState,
) -> ProcessCommand[Any]:
    """Build typed command for a step."""
    match step:
        case StatementReportStep.QUERY:
            return ProcessCommand(
                command_type="StatementQuery",
                data=StatementQueryRequest(
                    from_date=state.from_date,
                    to_date=state.to_date,
                    account_list=state.account_list,
                ),
            )
        # ... other steps
```

The `update_state` method uses typed responses to update state in place:

```python
def update_state(
    self,
    state: StatementReportState,
    step: StatementReportStep,
    reply: Reply,
) -> None:
    """Update state in place with data from typed reply."""
    match step:
        case StatementReportStep.QUERY:
            response = ProcessResponse.from_reply(reply, StatementQueryResponse)
            if response.result:
                state.query_result_path = response.result.result_path
        # ... other steps
```

### Java Translation

These Python dataclasses translate directly to Java records:

```java
// Request type
public record StatementQueryRequest(
    LocalDate fromDate,
    LocalDate toDate,
    List<String> accountList
) {}

// Response type
public record StatementQueryResponse(
    String resultPath
) {}

public record StatementRenderRequest(
    String aggregatedDataPath,
    OutputType outputType
) {}
```

Java records provide:
- Immutability (like Python's `frozen=True`)
- Automatic `equals()`, `hashCode()`, `toString()`
- Jackson serialization via `@JsonProperty` annotations

## Typed Process State

Process state is strongly typed using a mutable dataclass with explicit serialization methods.

### ProcessState Protocol

```python
from typing import Protocol, Self, Any

class ProcessState(Protocol):
    """Protocol for typed process state."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize state to JSON-compatible dict for database storage."""
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize state from JSON-compatible dict."""
        ...
```

### Example: StatementReportState

```python
from dataclasses import dataclass
from datetime import date
from typing import Any

@dataclass  # NOT frozen - state is mutable
class StatementReportState:
    """Typed state for statement report process."""

    # Initial data (set at start)
    from_date: date
    to_date: date
    account_list: list[str]
    output_type: OutputType

    # Accumulated from step responses (updated in place)
    query_result_path: str | None = None       # S3 path to query JSON
    aggregated_data_path: str | None = None    # S3 path to aggregated data
    rendered_file_path: str | None = None      # S3 path to final output

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_date": self.from_date.isoformat(),
            "to_date": self.to_date.isoformat(),
            "account_list": self.account_list,
            "output_type": self.output_type,
            "query_result_path": self.query_result_path,
            "aggregated_data_path": self.aggregated_data_path,
            "rendered_file_path": self.rendered_file_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StatementReportState":
        return cls(
            from_date=date.fromisoformat(data["from_date"]),
            to_date=date.fromisoformat(data["to_date"]),
            account_list=data["account_list"],
            output_type=OutputType(data["output_type"]),
            query_result_path=data.get("query_result_path"),
            aggregated_data_path=data.get("aggregated_data_path"),
            rendered_file_path=data.get("rendered_file_path"),
        )
```

### State Design Notes

- **Mutable state**: Fields are updated in place after each step completes
- **Explicit serialization**: `to_dict()` / `from_dict()` methods for JSON storage
- **Initial vs accumulated**: Fields with defaults are populated during process execution
- **Type safety**: IDE autocompletion and type checking for state access

## Step Name Enums

Step names use `StrEnum` for type safety while maintaining string compatibility.

### StrEnum Pattern

```python
from enum import StrEnum

class StatementReportStep(StrEnum):
    """Steps in statement report process."""
    QUERY = "statement_query"
    AGGREGATE = "statement_data_aggregation"
    RENDER = "statement_render"
```

### StrEnum Benefits

`StrEnum` (Python 3.11+) inherits from `str`, so it:
- Can be used anywhere a string is expected
- Serializes to JSON automatically as the string value
- Requires no explicit `.value` calls

```python
step = StatementReportStep.QUERY

# Works like a string
print(step)                           # "statement_query"
print(step == "statement_query")      # True
json.dumps({"step": step})            # '{"step": "statement_query"}'

# Database storage
current_step = step  # Stores as "statement_query" in VARCHAR column
```

### Java Translation

```java
public enum StatementReportStep {
    QUERY("statement_query"),
    AGGREGATE("statement_data_aggregation"),
    RENDER("statement_render");

    private final String value;

    StatementReportStep(String value) {
        this.value = value;
    }

    @JsonValue
    public String getValue() {
        return value;
    }

    @JsonCreator
    public static StatementReportStep fromValue(String value) {
        for (StatementReportStep step : values()) {
            if (step.value.equals(value)) {
                return step;
            }
        }
        throw new IllegalArgumentException("Unknown step: " + value);
    }
}

public enum OutputType {
    PDF("pdf"),
    HTML("html"),
    CSV("csv");

    private final String value;

    OutputType(String value) {
        this.value = value;
    }

    @JsonValue
    public String getValue() {
        return value;
    }

    @JsonCreator
    public static OutputType fromValue(String value) {
        for (OutputType type : values()) {
            if (type.value.equals(value)) {
                return type;
            }
        }
        throw new IllegalArgumentException("Unknown output type: " + value);
    }
}
```

## Process Manager Interface

### Marker Protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class ProcessManager(Protocol):
    """Marker interface for process managers."""

    @property
    def process_type(self) -> str:
        """Return the process type identifier."""
        ...

    @property
    def domain(self) -> str:
        """Return the domain this process operates in."""
        ...

    async def start(self, initial_data: dict[str, Any]) -> UUID:
        """Start a new process instance. Returns process_id."""
        ...

    async def handle_reply(self, reply: Reply, process: ProcessMetadata) -> None:
        """Handle a reply and advance the process."""
        ...
```

### Abstract Base Class

```python
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

TState = TypeVar("TState", bound="ProcessState")
TStep = TypeVar("TStep", bound=StrEnum)

class BaseProcessManager(ABC, Generic[TState, TStep]):
    """Base class for implementing process managers with typed state and steps."""

    def __init__(
        self,
        command_bus: CommandBus,
        process_repo: ProcessRepository,
        reply_queue: str,
    ):
        self.command_bus = command_bus
        self.process_repo = process_repo
        self.reply_queue = reply_queue

    @property
    @abstractmethod
    def process_type(self) -> str:
        """Return unique process type identifier."""
        pass

    @property
    @abstractmethod
    def domain(self) -> str:
        """Return the domain."""
        pass

    @abstractmethod
    def create_initial_state(self, initial_data: dict[str, Any]) -> TState:
        """Create typed state from initial input data."""
        pass

    async def start(self, initial_data: dict[str, Any]) -> UUID:
        """Start a new process instance."""
        process_id = uuid4()

        # Create typed state from input
        state = self.create_initial_state(initial_data)

        # Create process metadata
        process = ProcessMetadata[TState, TStep](
            domain=self.domain,
            process_id=process_id,
            process_type=self.process_type,
            status=ProcessStatus.PENDING,
            current_step=None,
            state=state,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            completed_at=None,
            error_code=None,
            error_message=None,
        )

        await self.process_repo.save(process)

        # Determine and execute first step
        first_step = self.get_first_step(state)
        await self._execute_step(process, first_step)

        return process_id

    @abstractmethod
    def get_first_step(self, state: TState) -> TStep:
        """Determine the first step based on initial state."""
        pass

    @abstractmethod
    async def build_command(
        self,
        step: TStep,
        state: TState,
    ) -> ProcessCommand[Any]:
        """Build typed command for a step.

        Returns: ProcessCommand with typed data
        """
        pass

    @abstractmethod
    def update_state(
        self,
        state: TState,
        step: TStep,
        reply: Reply,
    ) -> None:
        """Update state in place with data from reply."""
        pass

    @abstractmethod
    def get_next_step(
        self,
        current_step: TStep,
        reply: Reply,
        state: TState,
    ) -> TStep | None:
        """Determine next step based on reply and state.

        Returns:
          - TStep: Next step to execute
          - None: Process complete
        """
        pass

    async def handle_reply(
        self,
        reply: Reply,
        process: ProcessMetadata[TState, TStep],
    ) -> None:
        """Handle incoming reply and advance process."""

        # Update audit log
        await self._record_reply(process, reply)

        # Update state in place
        self.update_state(process.state, process.current_step, reply)

        # Handle failure
        if reply.outcome == ReplyOutcome.FAILED:
            await self._handle_failure(process, reply)
            return

        # Determine next step
        next_step = self.get_next_step(
            process.current_step,
            reply,
            process.state,
        )

        if next_step is None:
            # Process complete
            await self._complete_process(process)
        else:
            # Execute next step
            await self._execute_step(process, next_step)

    async def _execute_step(
        self,
        process: ProcessMetadata[TState, TStep],
        step: TStep,
    ) -> UUID:
        """Execute a single step by sending command."""
        command = await self.build_command(step, process.state)
        command_id = uuid4()

        await self.command_bus.send(
            domain=self.domain,
            command_type=command.command_type,
            command_id=command_id,
            data=command.data.to_dict(),
            correlation_id=process.process_id,  # Key: process_id as correlation
            reply_to=self.reply_queue,
        )

        # Update process
        process.current_step = step
        process.status = ProcessStatus.WAITING_FOR_REPLY
        process.updated_at = datetime.utcnow()

        # Record in audit log
        await self._record_command(process, step, command_id, command.command_type, command.data.to_dict())
        await self.process_repo.update(process)

        return command_id

    async def _complete_process(
        self,
        process: ProcessMetadata[TState, TStep],
    ) -> None:
        """Mark process as completed."""
        process.status = ProcessStatus.COMPLETED
        process.completed_at = datetime.utcnow()
        process.updated_at = datetime.utcnow()
        await self.process_repo.update(process)

    async def _handle_failure(
        self,
        process: ProcessMetadata[TState, TStep],
        reply: Reply,
    ) -> None:
        """Handle step failure. Override for custom behavior."""
        process.status = ProcessStatus.FAILED
        process.error_code = reply.error_code
        process.error_message = reply.error_message
        process.updated_at = datetime.utcnow()
        await self.process_repo.update(process)
```

## Reply Router

The Reply Router consumes the process reply queue and dispatches replies to the appropriate Process Manager:

```python
class ProcessReplyRouter:
    """Routes replies from process queue to appropriate process managers."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        process_repo: ProcessRepository,
        managers: dict[str, BaseProcessManager],  # process_type -> manager
        reply_queue: str,
    ):
        self.pool = pool
        self.process_repo = process_repo
        self.managers = managers
        self.reply_queue = reply_queue
        self.pgmq = PgmqClient()

    async def run(self, poll_interval: float = 1.0) -> None:
        """Run reply router continuously."""
        while True:
            async with self.pool.connection() as conn:
                messages = await self.pgmq.read(
                    self.reply_queue,
                    visibility_timeout=30,
                    batch_size=10,
                    conn=conn,
                )

                for msg in messages:
                    await self._process_reply(msg, conn)

            if not messages:
                await asyncio.sleep(poll_interval)

    async def _process_reply(
        self,
        msg: PgmqMessage,
        conn: AsyncConnection,
    ) -> None:
        """Process a single reply message."""
        reply = Reply(
            command_id=UUID(msg.message["command_id"]),
            correlation_id=UUID(msg.message["correlation_id"]) if msg.message.get("correlation_id") else None,
            outcome=ReplyOutcome(msg.message["outcome"]),
            data=msg.message.get("result"),
            error_code=msg.message.get("error_code"),
            error_message=msg.message.get("error_message"),
        )

        if reply.correlation_id is None:
            # No process association - skip
            await self.pgmq.delete(self.reply_queue, msg.msg_id, conn=conn)
            return

        # Look up process by correlation_id (which is the process_id)
        process = await self.process_repo.get_by_id(reply.correlation_id)

        if process is None:
            # Unknown process - log and skip
            logger.warning(f"Reply for unknown process: {reply.correlation_id}")
            await self.pgmq.delete(self.reply_queue, msg.msg_id, conn=conn)
            return

        # Find appropriate manager
        manager = self.managers.get(process.process_type)
        if manager is None:
            logger.error(f"No manager for process type: {process.process_type}")
            await self.pgmq.delete(self.reply_queue, msg.msg_id, conn=conn)
            return

        # Dispatch to manager
        try:
            await manager.handle_reply(reply, process)
            await self.pgmq.delete(self.reply_queue, msg.msg_id, conn=conn)
        except Exception as e:
            logger.exception(f"Error handling reply for process {process.process_id}")
            # Leave message for retry (visibility timeout will make it reappear)
```

## Example: Statement Report Process

```python
class StatementReportProcess(
    BaseProcessManager[StatementReportState, StatementReportStep]
):
    """Process manager for generating statement reports.

    Flow:
    1. StatementQuery - Query transaction data for accounts
    2. StatementDataAggregation - Aggregate raw data
    3. StatementRender - Render to requested output format
    """

    @property
    def process_type(self) -> str:
        return "StatementReport"

    @property
    def domain(self) -> str:
        return "reporting"

    def create_initial_state(self, initial_data: dict[str, Any]) -> StatementReportState:
        """Create typed state from initial input data."""
        return StatementReportState(
            from_date=date.fromisoformat(initial_data["from_date"]),
            to_date=date.fromisoformat(initial_data["to_date"]),
            account_list=initial_data["account_list"],
            output_type=OutputType(initial_data["output_type"]),
        )

    def get_first_step(self, state: StatementReportState) -> StatementReportStep:
        return StatementReportStep.QUERY

    async def build_command(
        self,
        step: StatementReportStep,
        state: StatementReportState,
    ) -> ProcessCommand[Any]:
        match step:
            case StatementReportStep.QUERY:
                return ProcessCommand(
                    command_type="StatementQuery",
                    data=StatementQueryRequest(
                        from_date=state.from_date,
                        to_date=state.to_date,
                        account_list=state.account_list,
                    ),
                )
            case StatementReportStep.AGGREGATE:
                return ProcessCommand(
                    command_type="StatementDataAggregation",
                    data=StatementDataAggregationRequest(
                        data_path=state.query_result_path,
                    ),
                )
            case StatementReportStep.RENDER:
                return ProcessCommand(
                    command_type="StatementRender",
                    data=StatementRenderRequest(
                        aggregated_data_path=state.aggregated_data_path,
                        output_type=state.output_type,
                    ),
                )

    def update_state(
        self,
        state: StatementReportState,
        step: StatementReportStep,
        reply: Reply,
    ) -> None:
        """Update state in place with data from reply."""
        match step:
            case StatementReportStep.QUERY:
                response = ProcessResponse.from_reply(reply, StatementQueryResponse)
                if response.result:
                    state.query_result_path = response.result.result_path
            case StatementReportStep.AGGREGATE:
                response = ProcessResponse.from_reply(reply, StatementDataAggregationResponse)
                if response.result:
                    state.aggregated_data_path = response.result.result_path
            case StatementReportStep.RENDER:
                response = ProcessResponse.from_reply(reply, StatementRenderResponse)
                if response.result:
                    state.rendered_file_path = response.result.result_path

    def get_next_step(
        self,
        current_step: StatementReportStep,
        reply: Reply,
        state: StatementReportState,
    ) -> StatementReportStep | None:
        """Determine next step based on current step."""
        match current_step:
            case StatementReportStep.QUERY:
                return StatementReportStep.AGGREGATE
            case StatementReportStep.AGGREGATE:
                return StatementReportStep.RENDER
            case StatementReportStep.RENDER:
                return None  # Process complete
```

### Starting the Process

```python
# Initialize
process_manager = StatementReportProcess(
    command_bus=command_bus,
    process_repo=process_repo,
    reply_queue="reporting__process_replies",
)

# Start a new statement report process
process_id = await process_manager.start({
    "from_date": "2024-01-01",
    "to_date": "2024-12-31",
    "account_list": ["ACC-001", "ACC-002", "ACC-003"],
    "output_type": "pdf",
})

# Process runs asynchronously via reply router
print(f"Started statement report process: {process_id}")
```

## Database Schema

### Process Table

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

### Process Audit Table

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

## Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────────────┐
│                              Application                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Process Manager Registry                         │   │
│  │  OrderFulfillmentProcess, PaymentProcess, RefundProcess, ...        │   │
│  └──────────────────────────────┬──────────────────────────────────────┘   │
│                                 │                                          │
│  ┌──────────────────────────────┴───────────────────────────────────────┐  │
│  │                     ProcessReplyRouter                               │  │
│  │  - Consumes process reply queue                                      │  │
│  │  - Looks up process by correlation_id                                │  │
│  │  - Dispatches to appropriate ProcessManager                          │  │
│  └──────────────────────────────┬───────────────────────────────────────┘  │
└─────────────────────────────────┼──────────────────────────────────────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    │   Process Reply Queue      │
                    │   (domain__process_replies)│
                    └─────────────┬──────────────┘
                                  │
         ┌────────────────────────┴─────────────────────────┐
         │                                                  │
         │              Reply (correlation_id=process_id)   │
         │                                                  │
         └────────────────────────┬─────────────────────────┘
                                  │
┌─────────────────────────────────┴──────────────────────────────────────────┐
│                           Command Bus Workers                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐ │
│  │ orders Worker   │  │ inventory Worker│  │ payments Worker             │ │
│  │ - ValidateOrder │  │ - ReserveInv    │  │ - ProcessPayment            │ │
│  │ - ShipOrder     │  │                 │  │                             │ │
│  │ - SendConfirm   │  │                 │  │                             │ │
│  └────────┬────────┘  └────────┬────────┘  └──────────────┬──────────────┘ │
│           │                    │                          │                │
│           └────────────────────┴──────────────────────────┘                │
│                                │                                           │
│                    Command (correlation_id=process_id, reply_to=queue)     │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

## Design Principles

### 1. Correlation ID is the Process ID

The `process_id` is used as the `correlation_id` for all commands sent by a process. This enables:
- Simple reply routing by correlation_id
- Natural grouping of related commands
- Audit trail correlation

### 2. State is Explicit JSON

Process state is stored as explicit JSON, not hidden in code:
- Enables inspection and debugging
- Supports process recovery after restart
- Allows external monitoring and dashboards

### 3. Steps are Named Operations

Each step has a name that:
- Maps to a command type via `build_command()`
- Determines next step via `get_next_step()`
- Records in audit log for traceability

### 4. Failures and Compensation

Failure handling integrates with the Troubleshooting Queue (TSQ):

1. **Transient failures** - CommandBus handles retries automatically
2. **Permanent failures / retries exhausted** - Command moves to TSQ
3. **Process waits** - Status becomes `WAITING_FOR_TSQ`
4. **Operator action**:
   - **Retry in TSQ** → Command retried, process continues normally on success
   - **Cancel in TSQ** → Process receives cancellation, triggers compensation
5. **Compensation** - Run compensating commands for completed steps in reverse order

```
Command fails → TSQ → Operator cancels → Process receives CANCELED reply
                                              │
                                              ▼
                                    Run compensations for
                                    completed steps (reverse order)
                                              │
                                              ▼
                                    Process status = COMPENSATED
```

## TSQ Integration

When a command is cancelled in the Troubleshooting Queue, the worker sends a reply with `outcome=CANCELED`. The Process Manager must handle this:

```python
async def handle_reply(self, reply: Reply, process: ProcessMetadata) -> None:
    if reply.outcome == ReplyOutcome.CANCELED:
        # Command was cancelled in TSQ - run compensations
        await self._run_compensations(process)
        return
    # ... normal flow
```

### Compensation Flow

```python
async def _run_compensations(self, process: ProcessMetadata) -> None:
    """Run compensating commands for completed steps in reverse order."""
    # Get completed steps from audit log
    completed_steps = await self._get_completed_steps(process)

    # Build compensation chain (reverse order)
    for step in reversed(completed_steps):
        comp_step = self.get_compensation_step(step)
        if comp_step:
            process.current_step = comp_step
            process.status = ProcessStatus.COMPENSATING
            await self.process_repo.update(process)

            # Execute compensation (fire-and-forget or wait for reply)
            await self._execute_step(process, comp_step)

    # Mark as compensated
    process.status = ProcessStatus.COMPENSATED
    process.completed_at = datetime.utcnow()
    await self.process_repo.update(process)
```

## Operational Considerations

### Process Recovery

If the application restarts, processes can be recovered:

```python
async def recover_processes(
    process_repo: ProcessRepository,
    managers: dict[str, BaseProcessManager],
) -> None:
    """Recover in-flight processes after restart."""

    # Find processes that were waiting for replies
    stuck_processes = await process_repo.find_by_status(
        [ProcessStatus.WAITING_FOR_REPLY]
    )

    for process in stuck_processes:
        # Check if reply is in queue (may have arrived during downtime)
        # Reply router will pick it up on next poll

        # Optionally: timeout check and retry or fail
        if process.updated_at < datetime.utcnow() - timedelta(hours=1):
            # Process stuck for too long - mark failed or retry
            ...
```

### Monitoring

Key metrics to track:
- Processes by status (in_progress, waiting, completed, failed)
- Process duration (created_at to completed_at)
- Step durations (sent_at to received_at in audit)

### Debugging

The audit log provides complete visibility:

```python
# Get full process history
audit_entries = await process_repo.get_audit_trail(process_id)

for entry in audit_entries:
    print(f"Step: {entry.step_name}")
    print(f"  Command: {entry.command_type} ({entry.command_id})")
    print(f"  Sent: {entry.sent_at}")
    print(f"  Reply: {entry.reply_outcome} at {entry.received_at}")
```

## Future Extensions

### Compensation (Saga Pattern)

Add compensation logic for rollback on failure:

```python
class CompensatingProcessManager(BaseProcessManager):

    @abstractmethod
    def get_compensation_step(self, failed_step: str) -> str | None:
        """Get compensation step for a failed step."""
        pass

    async def _handle_failure(self, process: ProcessMetadata, reply: Reply) -> None:
        # Build compensation chain from completed steps
        compensation_steps = []
        for entry in reversed(process.audit_log):
            if comp := self.get_compensation_step(entry.step_name):
                compensation_steps.append(comp)

        # Execute compensations
        for comp_step in compensation_steps:
            await self._execute_step(process, comp_step)
```

### Timeout Handling

Add step-level timeouts:

```python
@dataclass
class StepConfig:
    timeout: timedelta
    retry_on_timeout: bool = True

# In process manager
step_configs: dict[str, StepConfig] = {
    "process_payment": StepConfig(timeout=timedelta(seconds=30)),
    "ship_order": StepConfig(timeout=timedelta(minutes=5)),
}
```

### Conditional Steps

Support conditional step execution:

```python
def get_next_step(self, current_step, reply, state) -> str | None:
    match current_step:
        case "validate_order":
            if state.get("requires_approval"):
                return "request_approval"
            return "reserve_inventory"
```

## Skeleton Code - Module Structure

The following modules should be added to implement the Process Manager:

```
src/commandbus/
  process/
    __init__.py           # Public exports
    models.py             # ProcessMetadata, ProcessStatus, ProcessAuditEntry
    base.py               # BaseProcessManager abstract class
    router.py             # ProcessReplyRouter
    repository.py         # ProcessRepository protocol + PostgresProcessRepository
```

### src/commandbus/process/models.py

```python
"""Process Manager domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, StrEnum
from typing import Any, Generic, Protocol, Self, TypeVar
from uuid import UUID

from commandbus.models import ReplyOutcome


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
        """Serialize state to JSON-compatible dict for database storage."""
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Deserialize state from JSON-compatible dict."""
        ...


# Type variables for generic process metadata
TState = TypeVar("TState", bound=ProcessState)
TStep = TypeVar("TStep", bound=StrEnum)


@dataclass
class ProcessMetadata(Generic[TState, TStep]):
    """Metadata for a process instance with typed state and steps."""

    domain: str
    process_id: UUID
    process_type: str
    status: ProcessStatus = ProcessStatus.PENDING
    current_step: TStep | None = None  # StrEnum for step
    state: TState = None  # type: ignore[assignment]  # Typed process state

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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

    # Reply info (populated when received)
    reply_outcome: ReplyOutcome | None = None
    reply_data: dict[str, Any] | None = None
    received_at: datetime | None = None


@dataclass
class StepDefinition:
    """Configuration for a process step."""

    name: str
    command_type: str
    compensation_step: str | None = None
    timeout_seconds: int | None = None
```

### src/commandbus/process/repository.py

```python
"""Process repository for database persistence."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from commandbus.process.models import (
    ProcessAuditEntry,
    ProcessMetadata,
    ProcessStatus,
)

if TYPE_CHECKING:
    from psycopg import AsyncConnection


class ProcessRepository(Protocol):
    """Protocol for process persistence."""

    async def save(
        self,
        process: ProcessMetadata,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Save a new process."""
        ...

    async def update(
        self,
        process: ProcessMetadata,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Update existing process."""
        ...

    async def get_by_id(
        self,
        domain: str,
        process_id: UUID,
        conn: AsyncConnection | None = None,
    ) -> ProcessMetadata | None:
        """Get process by ID."""
        ...

    async def find_by_status(
        self,
        domain: str,
        statuses: list[ProcessStatus],
        conn: AsyncConnection | None = None,
    ) -> list[ProcessMetadata]:
        """Find processes by status."""
        ...

    async def log_step(
        self,
        domain: str,
        process_id: UUID,
        entry: ProcessAuditEntry,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Log a step execution to audit trail."""
        ...

    async def update_step_reply(
        self,
        domain: str,
        process_id: UUID,
        command_id: UUID,
        entry: ProcessAuditEntry,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Update step with reply information."""
        ...

    async def get_audit_trail(
        self,
        domain: str,
        process_id: UUID,
        conn: AsyncConnection | None = None,
    ) -> list[ProcessAuditEntry]:
        """Get full audit trail for a process."""
        ...

    async def get_completed_steps(
        self,
        domain: str,
        process_id: UUID,
        conn: AsyncConnection | None = None,
    ) -> list[str]:
        """Get list of completed step names (for compensation)."""
        ...


class PostgresProcessRepository:
    """PostgreSQL implementation of ProcessRepository."""

    def __init__(self, pool):
        self.pool = pool

    async def save(
        self,
        process: ProcessMetadata,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Save a new process."""
        query = """
            INSERT INTO commandbus.process (
                domain, process_id, process_type, status, current_step,
                state, error_code, error_message,
                created_at, updated_at, completed_at
            ) VALUES (
                %(domain)s, %(process_id)s, %(process_type)s, %(status)s, %(current_step)s,
                %(state)s, %(error_code)s, %(error_message)s,
                %(created_at)s, %(updated_at)s, %(completed_at)s
            )
        """
        params = {
            "domain": process.domain,
            "process_id": process.process_id,
            "process_type": process.process_type,
            "status": process.status.value,
            "current_step": process.current_step,
            "state": json.dumps(process.state),
            "error_code": process.error_code,
            "error_message": process.error_message,
            "created_at": process.created_at,
            "updated_at": process.updated_at,
            "completed_at": process.completed_at,
        }

        async def _execute(c: AsyncConnection) -> None:
            await c.execute(query, params)

        if conn:
            await _execute(conn)
        else:
            async with self.pool.connection() as c:
                await _execute(c)

    async def update(
        self,
        process: ProcessMetadata,
        conn: AsyncConnection | None = None,
    ) -> None:
        """Update existing process."""
        process.updated_at = datetime.utcnow()
        query = """
            UPDATE commandbus.process SET
                status = %(status)s,
                current_step = %(current_step)s,
                state = %(state)s,
                error_code = %(error_code)s,
                error_message = %(error_message)s,
                updated_at = %(updated_at)s,
                completed_at = %(completed_at)s
            WHERE domain = %(domain)s AND process_id = %(process_id)s
        """
        params = {
            "domain": process.domain,
            "process_id": process.process_id,
            "status": process.status.value,
            "current_step": process.current_step,
            "state": json.dumps(process.state),
            "error_code": process.error_code,
            "error_message": process.error_message,
            "updated_at": process.updated_at,
            "completed_at": process.completed_at,
        }

        async def _execute(c: AsyncConnection) -> None:
            await c.execute(query, params)

        if conn:
            await _execute(conn)
        else:
            async with self.pool.connection() as c:
                await _execute(c)

    async def get_by_id(
        self,
        domain: str,
        process_id: UUID,
        conn: AsyncConnection | None = None,
    ) -> ProcessMetadata | None:
        """Get process by ID."""
        query = """
            SELECT domain, process_id, process_type, status, current_step,
                   state, error_code, error_message,
                   created_at, updated_at, completed_at
            FROM commandbus.process
            WHERE domain = %(domain)s AND process_id = %(process_id)s
        """

        async def _execute(c: AsyncConnection) -> ProcessMetadata | None:
            async with c.cursor() as cur:
                await cur.execute(query, {"domain": domain, "process_id": process_id})
                row = await cur.fetchone()
                if row is None:
                    return None
                return self._row_to_metadata(row)

        if conn:
            return await _execute(conn)
        else:
            async with self.pool.connection() as c:
                return await _execute(c)

    def _row_to_metadata(self, row) -> ProcessMetadata:
        """Convert database row to ProcessMetadata."""
        return ProcessMetadata(
            domain=row[0],
            process_id=row[1],
            process_type=row[2],
            status=ProcessStatus(row[3]),
            current_step=row[4],
            state=row[5] if isinstance(row[5], dict) else json.loads(row[5]),
            error_code=row[6],
            error_message=row[7],
            created_at=row[8],
            updated_at=row[9],
            completed_at=row[10],
        )

    # ... additional methods follow same pattern
```

### src/commandbus/process/base.py

```python
"""Base Process Manager implementation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Generic, TypeVar
from uuid import uuid4

from commandbus.models import Reply, ReplyOutcome
from commandbus.process.models import (
    ProcessAuditEntry,
    ProcessCommand,
    ProcessMetadata,
    ProcessState,
    ProcessStatus,
)

if TYPE_CHECKING:
    from uuid import UUID

    from commandbus.bus import CommandBus
    from commandbus.process.repository import ProcessRepository

logger = logging.getLogger(__name__)

# Type variables for generic base class
TState = TypeVar("TState", bound=ProcessState)
TStep = TypeVar("TStep", bound=StrEnum)


class BaseProcessManager(ABC, Generic[TState, TStep]):
    """Base class for implementing process managers with typed state and steps."""

    def __init__(
        self,
        command_bus: CommandBus,
        process_repo: ProcessRepository,
        reply_queue: str,
    ):
        self.command_bus = command_bus
        self.process_repo = process_repo
        self.reply_queue = reply_queue

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

    @abstractmethod
    def create_initial_state(self, initial_data: dict[str, Any]) -> TState:
        """Create typed state from initial input data.

        Args:
            initial_data: Raw input data dict.

        Returns:
            Typed state instance.
        """
        pass

    async def start(self, initial_data: dict[str, Any]) -> UUID:
        """Start a new process instance.

        Args:
            initial_data: Initial state data for the process.

        Returns:
            The process_id (UUID) of the new process.
        """
        process_id = uuid4()

        # Create typed state from input
        state = self.create_initial_state(initial_data)

        process = ProcessMetadata[TState, TStep](
            domain=self.domain,
            process_id=process_id,
            process_type=self.process_type,
            status=ProcessStatus.PENDING,
            current_step=None,
            state=state,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await self.process_repo.save(process)

        # Determine and execute first step
        first_step = self.get_first_step(state)
        await self._execute_step(process, first_step)

        return process_id

    @abstractmethod
    def get_first_step(self, state: TState) -> TStep:
        """Determine the first step based on initial state."""
        pass

    @abstractmethod
    async def build_command(
        self,
        step: TStep,
        state: TState,
    ) -> ProcessCommand[Any]:
        """Build typed command for a step.

        Args:
            step: The step (StrEnum) to build command for.
            state: Current typed process state.

        Returns:
            ProcessCommand with typed data.
        """
        pass

    @abstractmethod
    def update_state(
        self,
        state: TState,
        step: TStep,
        reply: Reply,
    ) -> None:
        """Update state in place with data from reply.

        Args:
            state: Typed process state to update.
            step: The step that just completed.
            reply: The reply received.
        """
        pass

    @abstractmethod
    def get_next_step(
        self,
        current_step: TStep,
        reply: Reply,
        state: TState,
    ) -> TStep | None:
        """Determine next step based on reply and state.

        Args:
            current_step: The step that just completed.
            reply: The reply received.
            state: Current process state (after update_state).

        Returns:
            - TStep: Next step to execute
            - None: Process complete
        """
        pass

    def get_compensation_step(self, step: TStep) -> TStep | None:
        """Get compensation step for a given step.

        Override to provide compensation mapping.

        Args:
            step: The step that needs compensation.

        Returns:
            Compensation step, or None if no compensation needed.
        """
        return None

    async def handle_reply(
        self,
        reply: Reply,
        process: ProcessMetadata[TState, TStep],
    ) -> None:
        """Handle incoming reply and advance process.

        Args:
            reply: The reply received from command execution.
            process: The process metadata with typed state.
        """
        # Record reply in audit log
        await self._record_reply(process, reply)

        # Handle cancellation from TSQ - trigger compensation
        if reply.outcome == ReplyOutcome.CANCELED:
            logger.info(
                f"Process {process.process_id} command canceled in TSQ, "
                f"running compensations"
            )
            await self._run_compensations(process)
            return

        # Update state in place
        self.update_state(process.state, process.current_step, reply)

        # Handle failure (goes to TSQ, wait for operator)
        if reply.outcome == ReplyOutcome.FAILED:
            await self._handle_failure(process, reply)
            return

        # Determine next step
        next_step = self.get_next_step(
            process.current_step,
            reply,
            process.state,
        )

        if next_step is None:
            await self._complete_process(process)
        else:
            await self._execute_step(process, next_step)

    async def _execute_step(
        self,
        process: ProcessMetadata[TState, TStep],
        step: TStep,
    ) -> UUID:
        """Execute a single step by sending command."""
        command = await self.build_command(step, process.state)
        command_id = uuid4()

        await self.command_bus.send(
            domain=self.domain,
            command_type=command.command_type,
            command_id=command_id,
            data=command.data.to_dict(),
            correlation_id=process.process_id,
            reply_to=self.reply_queue,
        )

        process.current_step = step
        process.status = ProcessStatus.WAITING_FOR_REPLY
        process.updated_at = datetime.now(timezone.utc)

        # Record in audit log
        await self._record_command(
            process, step, command_id, command.command_type, command.data.to_dict()
        )
        await self.process_repo.update(process)

        return command_id

    async def _run_compensations(
        self,
        process: ProcessMetadata[TState, TStep],
    ) -> None:
        """Run compensating commands for completed steps in reverse order."""
        completed_steps = await self.process_repo.get_completed_steps(
            process.domain, process.process_id
        )

        for step in reversed(completed_steps):
            comp_step = self.get_compensation_step(step)
            if comp_step:
                process.current_step = comp_step
                process.status = ProcessStatus.COMPENSATING
                await self.process_repo.update(process)

                # Execute compensation and wait for reply
                await self._execute_step(process, comp_step)
                # Note: Reply router will call handle_reply for compensation replies

        process.status = ProcessStatus.COMPENSATED
        process.completed_at = datetime.now(timezone.utc)
        await self.process_repo.update(process)

    async def _complete_process(
        self,
        process: ProcessMetadata[TState, TStep],
    ) -> None:
        """Mark process as completed."""
        process.status = ProcessStatus.COMPLETED
        process.completed_at = datetime.now(timezone.utc)
        process.updated_at = datetime.now(timezone.utc)
        await self.process_repo.update(process)

    async def _handle_failure(
        self,
        process: ProcessMetadata[TState, TStep],
        reply: Reply,
    ) -> None:
        """Handle step failure - command is in TSQ."""
        process.status = ProcessStatus.WAITING_FOR_TSQ
        process.error_code = reply.error_code
        process.error_message = reply.error_message
        process.updated_at = datetime.now(timezone.utc)
        await self.process_repo.update(process)

    async def _record_command(
        self,
        process: ProcessMetadata[TState, TStep],
        step: TStep,
        command_id: UUID,
        command_type: str,
        command_data: dict[str, Any],
    ) -> None:
        """Record command execution in audit log."""
        entry = ProcessAuditEntry(
            step_name=step,  # StrEnum serializes as string
            command_id=command_id,
            command_type=command_type,
            command_data=command_data,
            sent_at=datetime.now(timezone.utc),
        )
        await self.process_repo.log_step(
            process.domain, process.process_id, entry
        )

    async def _record_reply(
        self,
        process: ProcessMetadata[TState, TStep],
        reply: Reply,
    ) -> None:
        """Update audit log with reply information."""
        entry = ProcessAuditEntry(
            step_name=process.current_step or "",
            command_id=reply.command_id,
            command_type="",  # Will be looked up
            command_data=None,
            sent_at=datetime.now(timezone.utc),  # Will be preserved
            reply_outcome=reply.outcome,
            reply_data=reply.data,
            received_at=datetime.now(timezone.utc),
        )
        await self.process_repo.update_step_reply(
            process.domain, process.process_id, reply.command_id, entry
        )

    async def _get_step_for_command(
        self,
        process: ProcessMetadata[TState, TStep],
        command_id: UUID,
    ) -> TStep:
        """Look up step name for a command from audit log."""
        audit_trail = await self.process_repo.get_audit_trail(
            process.domain, process.process_id
        )
        for entry in audit_trail:
            if entry.command_id == command_id:
                return entry.step_name
        raise ValueError(f"Command {command_id} not found in audit trail")
```

### src/commandbus/process/router.py

```python
"""Reply router for process managers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from commandbus.models import Reply, ReplyOutcome
from commandbus.pgmq.client import PgmqClient

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

    from commandbus.process.base import BaseProcessManager
    from commandbus.process.repository import ProcessRepository

logger = logging.getLogger(__name__)


class ProcessReplyRouter:
    """Routes replies from process queue to appropriate process managers."""

    def __init__(
        self,
        pool: AsyncConnectionPool,
        process_repo: ProcessRepository,
        managers: dict[str, BaseProcessManager],
        reply_queue: str,
    ):
        self.pool = pool
        self.process_repo = process_repo
        self.managers = managers
        self.reply_queue = reply_queue
        self.pgmq = PgmqClient()
        self._running = False

    async def run(
        self,
        poll_interval: float = 1.0,
        batch_size: int = 10,
    ) -> None:
        """Run reply router continuously."""
        self._running = True
        logger.info(f"ProcessReplyRouter starting on queue {self.reply_queue}")

        while self._running:
            try:
                async with self.pool.connection() as conn:
                    messages = await self.pgmq.read(
                        self.reply_queue,
                        visibility_timeout=30,
                        batch_size=batch_size,
                        conn=conn,
                    )

                    for msg in messages:
                        await self._process_reply(msg, conn)

                if not messages:
                    await asyncio.sleep(poll_interval)

            except Exception:
                logger.exception("Error in ProcessReplyRouter")
                await asyncio.sleep(poll_interval)

    def stop(self) -> None:
        """Stop the reply router."""
        self._running = False

    async def _process_reply(self, msg, conn) -> None:
        """Process a single reply message."""
        try:
            reply = Reply(
                command_id=UUID(msg.message["command_id"]),
                correlation_id=(
                    UUID(msg.message["correlation_id"])
                    if msg.message.get("correlation_id")
                    else None
                ),
                outcome=ReplyOutcome(msg.message["outcome"]),
                data=msg.message.get("result"),
                error_code=msg.message.get("error_code"),
                error_message=msg.message.get("error_message"),
            )

            if reply.correlation_id is None:
                logger.warning(f"Reply without correlation_id: {reply.command_id}")
                await self.pgmq.delete(self.reply_queue, msg.msg_id, conn=conn)
                return

            # correlation_id IS the process_id
            process = await self.process_repo.get_by_id(
                domain=self._extract_domain(msg),
                process_id=reply.correlation_id,
                conn=conn,
            )

            if process is None:
                logger.warning(
                    f"Reply for unknown process: {reply.correlation_id}"
                )
                await self.pgmq.delete(self.reply_queue, msg.msg_id, conn=conn)
                return

            manager = self.managers.get(process.process_type)
            if manager is None:
                logger.error(
                    f"No manager registered for process type: {process.process_type}"
                )
                await self.pgmq.delete(self.reply_queue, msg.msg_id, conn=conn)
                return

            # Dispatch to manager
            await manager.handle_reply(reply, process)
            await self.pgmq.delete(self.reply_queue, msg.msg_id, conn=conn)

        except Exception:
            logger.exception(f"Error processing reply message {msg.msg_id}")
            # Leave message for retry (visibility timeout will make it reappear)

    def _extract_domain(self, msg) -> str:
        """Extract domain from message or queue name."""
        if "domain" in msg.message:
            return msg.message["domain"]
        # Fall back to queue name convention: domain__process_replies
        return self.reply_queue.split("__")[0]
```

### src/commandbus/process/__init__.py

```python
"""Process Manager module for orchestrating multi-step command flows."""

from commandbus.process.base import BaseProcessManager
from commandbus.process.models import (
    ProcessAuditEntry,
    ProcessMetadata,
    ProcessState,
    ProcessStatus,
    StepDefinition,
)
from commandbus.process.repository import (
    PostgresProcessRepository,
    ProcessRepository,
)
from commandbus.process.router import ProcessReplyRouter

__all__ = [
    "BaseProcessManager",
    "PostgresProcessRepository",
    "ProcessAuditEntry",
    "ProcessMetadata",
    "ProcessReplyRouter",
    "ProcessRepository",
    "ProcessState",
    "ProcessStatus",
    "StepDefinition",
]
```

## Summary

The Process Manager pattern provides a clean abstraction for orchestrating multi-step command flows:

1. **Simple model**: Process ID as correlation ID, explicit state, named steps
2. **Reply-driven**: Progress via reply queue consumption
3. **Typed messages**: Type-safe request/response classes with explicit serialization
4. **Typed state**: Strongly typed process state with `to_dict()`/`from_dict()` serialization
5. **Step enums**: StrEnum for step names with IDE autocompletion and compile-time safety
6. **TSQ Integration**: Commands in troubleshooting queue pause the process; cancellation triggers compensation
7. **Compensation (Saga)**: Automatic rollback of completed steps on cancellation
8. **Auditable**: Complete command/reply history with timestamps
9. **Recoverable**: Database-persisted state enables restart recovery
10. **Extensible**: Generic base class (`BaseProcessManager[TState, TStep]`) with hooks for customization
11. **Cross-platform**: Python dataclasses and StrEnums translate directly to Java records and enums
