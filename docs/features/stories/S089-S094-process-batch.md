# Process Batch User Stories (S089-S094)

This document contains user stories for extending the existing batch infrastructure to support process batches, enabling aggregate completion monitoring for batches of processes.

## Overview

When creating multiple processes via `/processes/batch`, there's currently no way to monitor aggregate completion. Command batches don't help because a single process spawns multiple commands, and command completion doesn't mean process completion.

**Solution:** Extend the existing `commandbus.batch` table with a `batch_type` discriminator to support both command batches and process batches.

---

## S089: Extend Batch Schema for Process Batches

### User Story

As a developer, I want the batch table extended with a batch_type column so that batches can track either commands or processes.

### Acceptance Criteria

1. **AC1:** Migration V005 adds `batch_type TEXT NOT NULL DEFAULT 'COMMAND'` to `commandbus.batch`
2. **AC2:** Default value is 'COMMAND' for backward compatibility with existing batches
3. **AC3:** Process table gets `batch_id UUID` column (nullable)
4. **AC4:** Partial index `ix_process_batch_id` on `process(batch_id) WHERE batch_id IS NOT NULL`
5. **AC5:** Index `ix_process_batch_status` on `process(batch_id, status) WHERE batch_id IS NOT NULL` for efficient stats

### Technical Notes

```sql
ALTER TABLE commandbus.batch
ADD COLUMN batch_type TEXT NOT NULL DEFAULT 'COMMAND';

ALTER TABLE commandbus.process
ADD COLUMN batch_id UUID;

CREATE INDEX ix_process_batch_id
ON commandbus.process (batch_id)
WHERE batch_id IS NOT NULL;

CREATE INDEX ix_process_batch_status
ON commandbus.process (batch_id, status)
WHERE batch_id IS NOT NULL;
```

### Files to Modify

- `migrations/V005__batch_type_and_process_batch_id.sql` (new)

---

## S090: Process Batch Stats Refresh

### User Story

As a developer, I want a stored procedure to calculate process batch stats so that completion tracking works for process batches.

### Acceptance Criteria

1. **AC1:** `sp_refresh_batch_stats` updated to check `batch_type` column
2. **AC2:** When `batch_type = 'COMMAND'`, behavior unchanged (counts from `command` table)
3. **AC3:** When `batch_type = 'PROCESS'`, counts from `process` table instead
4. **AC4:** Process success states: `COMPLETED`, `COMPENSATED` → `completed_count`
5. **AC5:** Process failure states: `FAILED`, `CANCELED` → maps to `canceled_count` (reusing existing column)
6. **AC6:** Process in-progress states: `PENDING`, `IN_PROGRESS`, `WAITING_FOR_REPLY`, `WAITING_FOR_TSQ`, `COMPENSATING`

### Technical Notes

The existing `sp_refresh_batch_stats` needs conditional logic:

```sql
IF v_batch_type = 'PROCESS' THEN
    -- Count from process table
    SELECT
        COALESCE(SUM(CASE WHEN status IN ('COMPLETED', 'COMPENSATED') THEN 1 ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN status IN ('FAILED', 'CANCELED') THEN 1 ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN status NOT IN ('COMPLETED', 'COMPENSATED', 'FAILED', 'CANCELED') THEN 1 ELSE 0 END), 0)
    INTO v_completed, v_failed, v_in_progress
    FROM commandbus.process
    WHERE batch_id = p_batch_id;
ELSE
    -- Existing logic for command batches
    ...
END IF;
```

### Files to Modify

- `migrations/V005__batch_type_and_process_batch_id.sql`

---

## S091: Process Metadata Batch ID

### User Story

As a developer, I want ProcessMetadata to include batch_id so that processes can be linked to batches.

### Acceptance Criteria

1. **AC1:** `ProcessMetadata` dataclass has `batch_id: UUID | None = None` field
2. **AC2:** `ProcessSQL.SELECT_COLUMNS` includes `batch_id`
3. **AC3:** `ProcessSQL.SAVE` includes `batch_id` placeholder
4. **AC4:** `ProcessParams.save()` includes batch_id in parameter tuple
5. **AC5:** `ProcessParsers.from_row()` parses batch_id from row (handles None)

### Technical Notes

```python
# In ProcessMetadata
batch_id: UUID | None = None

# In ProcessSQL
SELECT_COLUMNS = """
    domain, process_id, process_type, status, current_step,
    state, error_code, error_message,
    created_at, updated_at, completed_at, batch_id
"""
```

### Files to Modify

- `src/commandbus/process/models.py`
- `src/commandbus/_core/process_sql.py`

---

## S092: Process Manager Batch Support

### User Story

As a developer, I want BaseProcessManager.start() to accept a batch_id so that processes can be created as part of a batch.

### Acceptance Criteria

1. **AC1:** `start(initial_data, batch_id=None)` signature accepts optional batch_id
2. **AC2:** When batch_id provided, ProcessMetadata is created with that batch_id
3. **AC3:** batch_id is persisted to database via repository
4. **AC4:** No batch existence validation (caller responsible for valid batch_id)

### Technical Notes

```python
async def start(
    self,
    initial_data: dict[str, Any],
    batch_id: UUID | None = None,
    conn: AsyncConnection[Any] | None = None,
) -> UUID:
    process = ProcessMetadata(
        domain=self.domain,
        process_id=uuid4(),
        process_type=self.process_type,
        state=self.create_initial_state(initial_data),
        batch_id=batch_id,  # NEW
    )
    ...
```

### Files to Modify

- `src/commandbus/process/base.py`
- `src/commandbus/process/repository.py` (if needed)

---

## S093: E2E Process Batch API

### User Story

As a user, I want the `/processes/batch` endpoint to create a batch so that I can monitor process batch completion.

### Acceptance Criteria

1. **AC1:** `POST /api/processes/batch` creates a batch record with `batch_type='PROCESS'`
2. **AC2:** Batch is created before starting processes
3. **AC3:** Each process is started with `batch_id` parameter
4. **AC4:** Response includes `batch_id` in addition to process list
5. **AC5:** `GET /api/batches/{batch_id}` returns batch with refreshed stats
6. **AC6:** Stats show process counts (not command counts)

### Technical Notes

```python
# In create_process_batch endpoint
batch = BatchMetadata(
    domain="reporting",
    batch_id=uuid4(),
    name=f"Process batch {datetime.now().isoformat()}",
    batch_type="PROCESS",  # NEW
    total_count=count,
    status=BatchStatus.PENDING,
)
await batch_repo.save(batch)

# Start processes with batch_id
for data in payloads:
    process_id = await process_manager.start(data, batch_id=batch.batch_id)
```

### Response Format

```json
{
  "batch_id": "uuid-here",
  "batch_status": "IN_PROGRESS",
  "total_count": 100,
  "completed_count": 0,
  "processes": [...]
}
```

### Files to Modify

- `tests/e2e/app/api/routes.py`

---

## S094: E2E Process Batch UI

### User Story

As a user, I want a UI page to view process batch status so that I can monitor completion.

### Acceptance Criteria

1. **AC1:** Process batch list page at `/process-batches` shows all process batches
2. **AC2:** List filtered to `batch_type='PROCESS'`
3. **AC3:** Process batch detail page at `/process-batches/{batch_id}`
4. **AC4:** Detail page shows: name, status, progress (completed/failed/total)
5. **AC5:** Detail page lists processes in the batch with links
6. **AC6:** Auto-refresh option to poll for status updates

### Files to Modify

- `tests/e2e/app/web/routes.py`
- `tests/e2e/app/templates/process_batch_list.html` (new)
- `tests/e2e/app/templates/process_batch_detail.html` (new)

---

## Implementation Order

1. **S089** - Schema migration (foundation)
2. **S090** - Stats refresh procedure (depends on S089)
3. **S091** - ProcessMetadata batch_id field (depends on S089)
4. **S092** - BaseProcessManager.start() batch support (depends on S091)
5. **S093** - E2E API integration (depends on S089, S092)
6. **S094** - E2E UI pages (depends on S093)

---

## Testing Strategy

### Unit Tests

- `ProcessMetadata` with batch_id serialization
- `ProcessParams.save()` includes batch_id
- `ProcessParsers.from_row()` handles batch_id

### Integration Tests

- Create process batch and verify stats refresh
- Process completion updates batch counts
- Multiple concurrent process batches

### E2E Tests

- Create batch via API, monitor completion
- Batch with failures shows COMPLETED_WITH_FAILURES
- UI pages render correctly
