# S045 - Batch Management UI View

## Parent Feature
F006 - E2E Testing & Demo Application

## User Story

**As a** user of the demo application
**I want** UI pages to create batches and monitor their progress
**So that** I can test batch functionality and track batch command completion

## Context

With the batch creation feature (S041) implemented in the commandbus library, the demo application needs corresponding UI views to create batches and monitor their progress. This extends the existing e2e demo application with batch management capabilities.

## Acceptance Criteria

### Scenario: Create batch via UI
**Given** I am on the batch creation page
**When** I specify batch name, command count, and behavior
**And** I click "Create Batch"
**Then** a batch is created with the specified commands
**And** I see a success message with the batch ID
**And** I am redirected to the batch detail page

### Scenario: View batch list
**Given** batches exist in the system
**When** I navigate to the batches page
**Then** I see a table of batches with name, status, and progress
**And** I can filter by status (PENDING, IN_PROGRESS, COMPLETED, COMPLETED_WITH_FAILURES)
**And** I see progress bars showing completion percentage

### Scenario: View batch detail
**Given** a batch exists
**When** I click on a batch in the list
**Then** I see batch metadata (name, created_at, status)
**And** I see progress counters (total, completed, failed, in_tsq)
**And** I see a list of commands in the batch with their statuses

### Scenario: Monitor batch progress in real-time
**Given** a batch is being processed
**When** I am on the batch detail page
**Then** the progress counters update automatically
**And** the status transitions when all commands complete

### Scenario: Link to batch from command detail
**Given** a command belongs to a batch
**When** I view the command in the commands browser
**Then** I see a link to the parent batch
**And** clicking it takes me to the batch detail page

## UI Design

### New Pages

#### 1. Batches List Page (`/batches`)
```
+------------------------------------------+
| Batches                      [Create New] |
+------------------------------------------+
| Filter: [Status ▼] [Apply]               |
+------------------------------------------+
| Name          | Status    | Progress     |
|---------------|-----------|--------------|
| Monthly Run   | COMPLETED | ████████ 100%|
| Import Job 1  | IN_PROG   | ████░░░░  50%|
| Test Batch    | PENDING   | ░░░░░░░░   0%|
+------------------------------------------+
| < Prev  Page 1 of 3  Next >              |
+------------------------------------------+
```

#### 2. Create Batch Page (`/batches/new`)
```
+------------------------------------------+
| Create New Batch                          |
+------------------------------------------+
| Batch Name: [________________________]   |
|                                          |
| Number of Commands: [10    ]             |
|                                          |
| Command Behavior:                        |
| ( ) Success                              |
| ( ) Fail Permanent                       |
| ( ) Fail Transient Then Succeed          |
|                                          |
| Execution Time (ms): [100   ]            |
|                                          |
| [Create Batch]                           |
+------------------------------------------+
```

#### 3. Batch Detail Page (`/batches/<batch_id>`)
```
+------------------------------------------+
| Batch: Monthly Run                        |
| Status: IN_PROGRESS                       |
| Created: 2024-01-15 10:30:00             |
+------------------------------------------+
| Progress                                  |
| ████████████░░░░░░░░ 60%                 |
|                                          |
| Total: 100  Completed: 60  Failed: 0     |
| In TSQ: 0   Canceled: 0                  |
+------------------------------------------+
| Commands                                  |
+------------------------------------------+
| Command ID    | Type    | Status         |
|---------------|---------|----------------|
| abc123...     | TestCmd | COMPLETED      |
| def456...     | TestCmd | IN_PROGRESS    |
| ghi789...     | TestCmd | PENDING        |
+------------------------------------------+
```

### Navigation Updates
- Add "Batches" link to sidebar navigation
- Add batch_id column to commands browser table (when applicable)

## API Endpoints

### New Endpoints

```python
# tests/e2e/app/api/routes.py

@api_router.post("/batches")
async def create_batch(request: CreateBatchRequest) -> CreateBatchResponse:
    """Create a new batch with test commands."""
    pass

@api_router.get("/batches")
async def list_batches(
    status: str | None = None,
    limit: int = 20,
    offset: int = 0
) -> ListBatchesResponse:
    """List batches with optional status filter."""
    pass

@api_router.get("/batches/{batch_id}")
async def get_batch(batch_id: UUID) -> BatchDetailResponse:
    """Get batch details with command summary."""
    pass

@api_router.get("/batches/{batch_id}/commands")
async def get_batch_commands(
    batch_id: UUID,
    limit: int = 50,
    offset: int = 0
) -> ListCommandsResponse:
    """Get commands belonging to a batch."""
    pass
```

### Request/Response Schemas

```python
# tests/e2e/app/api/schemas.py

@dataclass
class CreateBatchRequest:
    name: str
    command_count: int
    behavior: str  # success, fail_permanent, fail_transient_then_succeed
    execution_time_ms: int = 100

@dataclass
class CreateBatchResponse:
    batch_id: UUID
    total_commands: int

@dataclass
class BatchSummary:
    batch_id: UUID
    name: str | None
    status: str
    total_count: int
    completed_count: int
    failed_count: int
    in_troubleshooting_count: int
    created_at: datetime

@dataclass
class ListBatchesResponse:
    batches: list[BatchSummary]
    total: int
    limit: int
    offset: int
```

## Files to Create

- `tests/e2e/app/templates/pages/batches.html` - Batch list page
- `tests/e2e/app/templates/pages/batch_new.html` - Create batch form
- `tests/e2e/app/templates/pages/batch_detail.html` - Batch detail page
- `tests/e2e/app/static/js/batches.js` - Batch page JavaScript

## Files to Modify

- `tests/e2e/app/api/routes.py` - Add batch API endpoints
- `tests/e2e/app/api/schemas.py` - Add batch schemas
- `tests/e2e/app/web/routes.py` - Add batch page routes
- `tests/e2e/app/templates/includes/sidebar.html` - Add Batches nav link
- `tests/e2e/app/templates/pages/commands.html` - Add batch_id column

## Definition of Done

- [ ] Batches list page with status filter and pagination
- [ ] Create batch form with configurable command count and behavior
- [ ] Batch detail page with progress counters
- [ ] Commands listed under batch with status
- [ ] Auto-refresh of batch progress (polling or SSE)
- [ ] Batch link visible in commands browser
- [ ] Navigation updated with Batches link
- [ ] Responsive design with Tailwind CSS

## Story Size
M (2000-5000 tokens)

## Priority
Should Have

## Dependencies
- S041 - Create Batch with Commands (commandbus library)
- S017 - Base Infrastructure Setup
- S019 - Commands Browser View
