# S043: Receive Callback on Batch Completion

## Parent Feature

[F009 - Batch Commands](../F009-batch-commands.md)

## User Story

**As a** application developer
**I want** to receive an async callback when a batch completes
**So that** I can trigger follow-up actions without polling

## Context

When all commands in a batch reach terminal states (COMPLETED, FAILED, or CANCELED - after TSQ resolution), the application may need to perform follow-up actions like sending notifications, updating external systems, or starting dependent workflows. An async callback provides an event-driven alternative to polling.

## Acceptance Criteria (Given-When-Then)

### Scenario: Callback invoked on successful batch completion

**Given** a batch created with on_complete callback registered
**And** all 3 commands in the batch complete successfully
**When** the last command completes
**Then** the on_complete callback is invoked with BatchMetadata
**And** the BatchMetadata includes:
  - batch_id matching the batch
  - status: "COMPLETED"
  - completed_count: 3
  - completed_at: set to completion timestamp

### Scenario: Callback invoked on batch completion with failures

**Given** a batch created with on_complete callback registered
**And** the batch has 2 completed commands and 1 canceled (after TSQ)
**When** the operator cancels the TSQ command
**Then** the on_complete callback is invoked with BatchMetadata
**And** the BatchMetadata includes:
  - status: "COMPLETED_WITH_FAILURES"
  - completed_count: 2
  - canceled_count: 1

### Scenario: Callback not invoked while commands in TSQ

**Given** a batch with on_complete callback registered
**And** the batch has 2 completed commands and 1 in TSQ
**Then** the callback is NOT invoked
**And** the batch remains in "IN_PROGRESS" status

### Scenario: Callback error does not affect batch completion

**Given** a batch with on_complete callback that raises an exception
**When** the batch completes
**Then** the callback exception is logged
**And** the batch status is still "COMPLETED"
**And** the BATCH_COMPLETED audit event is still recorded
**And** no exception is propagated to the worker

### Scenario: No callback registered

**Given** a batch created without on_complete callback
**When** the batch completes
**Then** the batch status changes to "COMPLETED"
**And** the BATCH_COMPLETED audit event is recorded
**And** no callback invocation is attempted

### Scenario: Callback receives accurate final state

**Given** a batch with multiple concurrent command completions
**When** the last command completes and triggers the callback
**Then** the callback receives the final accurate BatchMetadata
**And** all counts reflect the true final state

### Scenario: Callback registry survives worker restart (best effort)

**Given** a batch with callback registered
**When** the worker process restarts before batch completion
**Then** the callback is lost (not persisted)
**And** the batch still completes normally
**And** applications should poll for completion as fallback

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Callback invoked on success | Integration | `tests/integration/test_batch.py::test_batch_callback_on_complete` |
| Callback receives metadata | Integration | `tests/integration/test_batch.py::test_batch_callback_metadata` |
| Callback on COMPLETED_WITH_FAILURES | Integration | `tests/integration/test_batch.py::test_batch_callback_with_failures` |
| Callback not called with TSQ pending | Integration | `tests/integration/test_batch.py::test_batch_callback_not_called_with_tsq` |
| Callback error handled | Integration | `tests/integration/test_batch.py::test_batch_callback_error_handled` |
| No callback OK | Unit | `tests/unit/test_batch.py::test_batch_no_callback` |

## Story Size

M (2000-4000 tokens, medium feature)

## Priority (MoSCoW)

Should Have

## Dependencies

- S041 (Create batch) completed
- S042 (Batch status tracking) completed

## Technical Notes

### Callback Registry

```python
# Global in-memory registry
_batch_callbacks: dict[tuple[str, UUID], BatchCompletionCallback] = {}

def register_batch_callback(
    domain: str,
    batch_id: UUID,
    callback: BatchCompletionCallback,
) -> None:
    _batch_callbacks[(domain, batch_id)] = callback

def get_batch_callback(
    domain: str,
    batch_id: UUID,
) -> BatchCompletionCallback | None:
    return _batch_callbacks.get((domain, batch_id))

def remove_batch_callback(domain: str, batch_id: UUID) -> None:
    _batch_callbacks.pop((domain, batch_id), None)
```

### Callback Invocation

Callback should be invoked by the worker/TSQ operation that triggers batch completion:

```python
async def _check_and_invoke_batch_callback(
    domain: str,
    batch_id: UUID,
    batch_repo: BatchRepository,
) -> None:
    callback = get_batch_callback(domain, batch_id)
    if callback is None:
        return

    batch = await batch_repo.get(domain, batch_id)
    if batch is None or batch.status not in ("COMPLETED", "COMPLETED_WITH_FAILURES"):
        return

    try:
        await callback(batch)
    except Exception as e:
        logger.exception(f"Batch callback error for {batch_id}: {e}")
    finally:
        remove_batch_callback(domain, batch_id)
```

### Thread Safety

- Use threading.Lock or asyncio.Lock for registry access if needed
- Callback invocation should be outside any database transactions

## LLM Agent Instructions

**Reference Files:**
- `src/commandbus/batch.py` - New module for callback registry
- `src/commandbus/worker.py` - Check for batch completion after command complete
- `src/commandbus/ops/troubleshooting.py` - Check for batch completion after TSQ ops
- `src/commandbus/repositories/batch.py` - Get batch for callback

**Constraints:**
- Callbacks are async functions
- Callback exceptions must not propagate to caller
- Callbacks are in-memory only (not persisted)
- Callback invoked exactly once per batch completion
- Callback receives final, accurate batch state

**Verification Steps:**
1. Run `pytest tests/integration/test_batch.py::test_batch_callback* -v`
2. Verify callback receives accurate metadata
3. Verify callback errors are handled gracefully

## Definition of Done

- [ ] Code complete and reviewed
- [ ] Callback registry implemented
- [ ] Unit tests written and passing
- [ ] Integration tests written and passing
- [ ] Error handling verified
- [ ] Acceptance criteria verified
- [ ] No regressions in related functionality
