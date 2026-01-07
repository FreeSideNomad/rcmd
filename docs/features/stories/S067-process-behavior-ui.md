# S067: Configure Reporting Process Behavior & High-Volume Batches

## User Story

As an E2E tester, I want to configure probabilistic behavior for StatementReport process steps from the UI and create up to 100,000 processes in one batch so that I can stress-test reporting flows under realistic failure patterns at scale.

## Acceptance Criteria

### AC1: UI Behavior Controls
- Given I open the "Create Process Batch" UI
- When I expand the behavior section
- Then I can configure `CommandBehavior` sliders/inputs for each step (Query, Aggregation, Render) using the same fields as single-command creation (failure %, timeout %, durations, response data)
- And defaults remain zeroed if I leave the section collapsed

### AC2: API Schema & Validation
- Given I submit the batch create form
- When the API validates the payload
- Then `ProcessBatchCreateRequest` accepts an optional `behavior` object with `query`, `aggregation`, and `render` `CommandBehavior` entries
- And the `count` field allows values up to 100,000 with a clear validation error beyond that limit

### AC3: Process State & Command Registration
- Given a process batch is created with behavior settings
- When StatementReportProcess executes a step
- Then it stores the selected step behavior in `e2e.test_command` for the generated `command_id`
- And reporting handlers call `_get_behavior` / `_handle_probabilistic` with that configuration before executing

### AC4: Default Behavior Compatibility
- Given no behavior is supplied
- When StatementReportProcess sends commands
- Then no `test_command` record is created and handlers fall back to deterministic execution (no failures, no delays)
- And existing load/batch tools continue to work without behavior data

### AC5: High-Volume Batch Creation
- Given I request 100,000 processes
- When the API runs
- Then it chunks creation work to avoid blocking (e.g., `asyncio.gather` or batched writes)
- And it returns once all processes are persisted, with the list view reflecting the larger total

### AC6: Test Coverage
- Unit tests cover:
  - Behavior mapping from request -> state -> repository row
  - StatementReportProcess inserting `test_command` entries when behavior exists
  - Validation rejecting counts > 100,000
- Integration/E2E tests cover:
  - Reporting handler reading configured behavior (force deterministic failure/sleep)
  - Batch creation path supporting high count inputs (can be a reduced-count smoke test)

## Implementation Notes

1. **Schemas & UI**
   - Add `ProcessStepBehavior` (query/aggregation/render `CommandBehavior`) to `tests/e2e/app/api/schemas.py`.
   - Update `ProcessBatchCreateRequest` to include `behavior: ProcessStepBehavior | None` and set `count` max to 100_000.
   - Surface the new inputs in the React/HTMX(?) form under `tests/e2e/app/web/templates/processes.html` (reuse the existing behavior partial if possible).

2. **Persistence**
   - Extend `StatementReportState` to store optional `behavior` dict keyed by `StatementReportStep`.
   - Inject `TestCommandRepository` into `StatementReportProcess` and override `_execute_step` (or add a hook in `BaseProcessManager`) to:
     1. Create a `test_command` row with the resolved behavior before sending the command when behavior exists.
     2. Skip repository writes when behavior is absent.

3. **Routing**
   - When creating processes in `create_process_batch`, pass the behavior payload into initial state (e.g., `initial_data["behavior"] = {...}`).
   - Ensure reply router + handlers don’t require changes beyond reading behavior via existing helper.

4. **Scalability**
   - Increase API & UI validation to allow 100k processes.
   - Optimize batch creation loop (`range(request.count)`) by chunking into slices (e.g., batches of 1k) or using background tasks so the request doesn’t exceed timeouts.

5. **Testing**
   - Unit tests for the new schema/model serialization, state hydration, and behavior injection.
   - Integration test that preconfigures behavior (e.g., 100% permanent failure on render) and asserts the reporting handler raises the expected error.
   - Smoke test for creating a large batch (reduced count) to ensure no regressions.
