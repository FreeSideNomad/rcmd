# S063: E2E StatementReportProcess Handlers

## User Story

As a tester, I want StatementReportProcess handlers in the E2E app so that I can demonstrate and test the process manager flow.

## Acceptance Criteria

### AC1: StatementQuery Handler
- Given a StatementQuery command is received
- When the handler processes it
- Then it returns `{"result_path": "s3://bucket/query/{uuid}.json"}`

### AC2: StatementDataAggregation Handler
- Given a StatementDataAggregation command is received
- When the handler processes it
- Then it returns `{"result_path": "s3://bucket/aggregated/{uuid}.json"}`

### AC3: StatementRender Handler
- Given a StatementRender command is received
- When the handler processes it
- Then it returns `{"result_path": "s3://bucket/rendered/{uuid}.{output_type}"}`

### AC4: Handler Registration
- Given handlers are defined
- When the E2E app starts
- Then all three handlers are registered for the "reporting" domain

### AC5: Probabilistic Behavior Support
- Given probabilistic behaviors are configured
- When handlers execute
- Then they can simulate failures based on configuration

### AC6: StatementReportProcess Implementation
- Given the process manager pattern is implemented
- When StatementReportProcess is created
- Then it properly chains Query -> Aggregate -> Render steps

### AC7: State Types Implementation
- Given typed state is needed
- When StatementReportState is used
- Then it has: from_date, to_date, account_list, output_type, and result paths

### AC8: Reporting Domain Worker
- Given the "reporting" domain has registered handlers
- When the E2E app starts
- Then a Worker is started for the "reporting" domain queue that:
  1. Consumes commands from `reporting__commands` queue
  2. Dispatches to registered handlers (StatementQuery, StatementDataAggregation, StatementRender)
  3. Sends replies to the `reply_to` queue specified in each command

### AC9: Process Reply Router
- Given StatementReportProcess sends commands with `reply_to=reporting__process_replies`
- When the E2E app starts
- Then a ProcessReplyRouter is started that:
  1. Consumes from `reporting__process_replies` queue
  2. Looks up process by `correlation_id`
  3. Dispatches to StatementReportProcess.handle_reply()
  4. Advances the process to next step

### AC10: Reply Queue Creation
- Given process replies need a dedicated queue
- When the E2E app initializes
- Then the `reporting__process_replies` PGMQ queue is created

## Implementation Notes

- Handlers: `tests/e2e/app/handlers/reporting.py`
- Process: `tests/e2e/app/process/statement_report.py`
- Worker/Router setup: `tests/e2e/app/main.py`
- Use existing handler patterns from `tests/e2e/app/handlers/`
- Mock S3 paths (no actual S3 interaction needed)

## Worker and Router Setup

```python
# In tests/e2e/app/main.py

from commandbus.worker import Worker
from commandbus.process.router import ProcessReplyRouter

# Create handler registry for "reporting" domain
reporting_registry = HandlerRegistry()
reporting_registry.register("StatementQuery", StatementQueryHandler())
reporting_registry.register("StatementDataAggregation", StatementDataAggregationHandler())
reporting_registry.register("StatementRender", StatementRenderHandler())

# Create and start worker for reporting domain
reporting_worker = Worker(
    pool=pool,
    domain="reporting",
    handler_registry=reporting_registry,
)

# Create StatementReportProcess manager
statement_report_process = StatementReportProcess(
    command_bus=command_bus,
    process_repo=process_repo,
    reply_queue="reporting__process_replies",
)

# Create and start ProcessReplyRouter
process_router = ProcessReplyRouter(
    pool=pool,
    process_repo=process_repo,
    managers={"StatementReport": statement_report_process},
    reply_queue="reporting__process_replies",
)

# Start both as background tasks
@app.on_event("startup")
async def startup():
    # Ensure reply queue exists
    await pgmq.create_queue("reporting__process_replies")

    # Start worker and router
    asyncio.create_task(reporting_worker.run())
    asyncio.create_task(process_router.run())
```

## Handler Code

```python
from dataclasses import dataclass
from uuid import uuid4

@dataclass
class StatementQueryHandler:
    """Handler for StatementQuery command."""

    async def handle(self, command) -> dict:
        # Simulate query execution, return mock S3 path
        return {
            "result_path": f"s3://e2e-bucket/query/{uuid4()}.json"
        }

@dataclass
class StatementDataAggregationHandler:
    """Handler for StatementDataAggregation command."""

    async def handle(self, command) -> dict:
        # Uses data_path from command, returns aggregated result
        return {
            "result_path": f"s3://e2e-bucket/aggregated/{uuid4()}.json"
        }

@dataclass
class StatementRenderHandler:
    """Handler for StatementRender command."""

    async def handle(self, command) -> dict:
        output_type = command.data.get("output_type", "pdf")
        return {
            "result_path": f"s3://e2e-bucket/rendered/{uuid4()}.{output_type}"
        }
```

## State and Step Types

```python
from enum import StrEnum
from dataclasses import dataclass
from datetime import date

class OutputType(StrEnum):
    PDF = "pdf"
    HTML = "html"
    CSV = "csv"

class StatementReportStep(StrEnum):
    QUERY = "statement_query"
    AGGREGATE = "statement_data_aggregation"
    RENDER = "statement_render"

@dataclass
class StatementReportState:
    from_date: date
    to_date: date
    account_list: list[str]
    output_type: OutputType
    query_result_path: str | None = None
    aggregated_data_path: str | None = None
    rendered_file_path: str | None = None
```

## Verification

- [ ] All three handlers registered and working
- [ ] Handlers return expected response format
- [ ] Process chains steps correctly
- [ ] State accumulates result paths
- [ ] Process completes successfully with all three steps
- [ ] Reporting domain worker consumes and processes commands
- [ ] Worker sends replies to correct reply_to queue
- [ ] ProcessReplyRouter consumes from process replies queue
- [ ] ProcessReplyRouter advances process through all steps
- [ ] Full end-to-end flow: start process -> 3 commands -> 3 replies -> COMPLETED
