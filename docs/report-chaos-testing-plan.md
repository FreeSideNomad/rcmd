# Report Process Chaos Testing Plan

## Overview

Goal: allow the E2E StatementReport process to run chaos-style scenarios by configuring probabilistic behavior (failures/timeouts/delays) per step from the UI, while scaling batch creation up to 100,000 processes. This document outlines the architecture and implementation plan.

## Current State

- `tests/e2e/app/handlers/reporting.py` already supports probabilistic execution via `_get_behavior` and `_handle_probabilistic`, reading behavior from `e2e.test_command` keyed by `command_id`.
- `ProcessBatchCreateRequest` only exposes `count`, dates, and `output_type`; behavior cannot be set for process steps.
- StatementReport process commands are created dynamically inside `BaseProcessManager._execute_step` with new UUIDs, so handlers cannot see the process state directly.
- Batch creation limit is capped at 100 processes.

## Design Goals

1. UI/API can submit behavior settings (same `CommandBehavior` schema) for each StatementReport step (Query, Aggregation, Render).
2. StatementReportProcess stores the behavior config in its typed state so each step knows what to apply.
3. For every dynamically created step command, we materialize the behavior into `e2e.test_command` so reporting handlers retrieve it via `_get_behavior`.
4. Raise process batch limit to 100,000 and chunk creation so API calls remain responsive.
5. Preserve backwards compatibility: if no behavior is supplied, nothing is written to `test_command` and handlers run deterministically.

## Implementation Plan

### 1. Schema & UI Updates
- Extend `tests/e2e/app/api/schemas.py` with `ProcessStepBehavior`:
  ```python
  class ProcessStepBehavior(BaseModel):
      query: CommandBehavior | None = None
      aggregation: CommandBehavior | None = None
      render: CommandBehavior | None = None
  ```
- Update `ProcessBatchCreateRequest`:
  ```python
  class ProcessBatchCreateRequest(BaseModel):
      count: int = Field(default=1, ge=1, le=100_000)
      behavior: ProcessStepBehavior | None = None
      ...
  ```
- Mirror the behavior form controls in the process batch UI template (e.g., collapsible panel allowing per-step configuration, reusing the existing `CommandBehavior` partial).

### 2. Process State Changes
- Update `StatementReportState` (in `tests/e2e/app/process/statement_report.py`) to hold optional per-step behavior:
  ```python
  @dataclass
  class StatementReportState(ProcessState):
      behavior: dict[str, dict[str, Any]] | None = None
  ```
- Ensure `to_dict` / `from_dict` serialize/deserialise the behavior map.
- When `create_process_batch` builds `initial_data`, include `behavior` if provided.

### 3. Behavior Materialization
- Inject `TestCommandRepository` into `StatementReportProcess` (constructor param, store on `self._behavior_repo`).
- Override `_execute_step` (or add a helper) to:
  1. Pull the behavior for the current `step` from `process.state.behavior`.
  2. If present, call `TestCommandRepository.create(command_id, behavior, payload={"process_step": step})` before `command_bus.send`.
  3. If absent, skip the insert.
- This matches how `TestCommandHandlers` operate, allowing `ReportingHandlers` to reuse `_get_behavior` unchanged.

### 4. High-Volume Batch Creation
- In `create_process_batch` (API route), increase the allowed count to 100k.
- Optimize the creation loop to avoid blocking:
  - Process in chunks (e.g., batches of 500–1,000 processes per iteration) to yield back to the event loop.
  - Optionally use `asyncio.gather` with bounded concurrency if we parallelize `report_process.start` calls.
- Provide user feedback (toast/progress) indicating large batches may take longer.

### 5. Testing Strategy
- **Unit tests**:
  - Schema serialization for `ProcessStepBehavior`.
  - `StatementReportProcess` writing to `TestCommandRepository` when behavior exists (mock repo to assert calls).
  - Validation that counts > 100,000 raise `422`.
- **Integration tests**:
  - Create a process batch with 100% permanent failure on render; assert `handle_render` raises `PermanentCommandError` via existing `_get_behavior` path.
  - Smoke test for high-count creation (reduced to e.g., 5k) to ensure chunking works.
- **E2E/Manual**:
  - Drive the UI to configure per-step chaos parameters and observe the behavior in dashboards and audit trail.

## Future Considerations

- Allow linking behavior configs via presets (e.g., saved chaos profiles) instead of per-request JSON.
- Expand reporting domain to honor behavior when sending replies (e.g., custom response payloads for the render step).
- Surface behavior state on the process detail page for observability.
