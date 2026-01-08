# S071: Settings UI Runtime Toggle

## Parent Feature

[F014 - Synchronous Wrappers & Runtime Toggle](../F014-sync-wrapper.md)

## User Story

**As an** operator using the E2E settings panel
**I want** to switch between async and sync runtimes from the browser
**So that** I can reconfigure the system without editing environment variables or code.

## Context

With runtime config persisted (S070), the FastAPI API exposes the flag but the UI only shows worker/retry forms. This story adds a new card on `/settings` plus client-side logic to submit runtime updates. It also educates users to restart workers after changing the mode.

## Acceptance Criteria

### Scenario: Runtime controls visible
**Given** I open `/settings`
**When** the page loads
**Then** I see a Runtime Mode card with:
  - Radio buttons (or select) for `Async` vs `Sync`
  - Optional numeric input for Thread Pool Size
  - Helper text describing restart requirements.

### Scenario: Runtime values load from API
**Given** the API returns `runtime.mode="sync"` and `thread_pool_size=8`
**When** the page initializes
**Then** the radio button for Sync is selected and the numeric input displays 8.

### Scenario: Saving runtime updates backend
**Given** I change the mode or pool size and submit the form
**When** the API responds successfully
**Then** the UI shows a success toast like “Runtime settings saved (restart workers to apply)”
**And** the next `/config` call reflects the change.

### Scenario: Handling null thread pool size
**Given** thread pool size is cleared
**When** I submit the form
**Then** the payload omits or sends `null`, causing the backend to use defaults without validation errors.

## Technical Notes

- File: `tests/e2e/app/templates/pages/settings.html`
  - Add new card markup consistent with Tailwind styling used elsewhere.
  - Extend script block to:
    - Populate runtime fields in `loadConfig()`.
    - Submit runtime payload via `api.put('/config', { runtime: {...} })`.
    - Share `showMessage()` helper with existing forms or add runtime-specific messaging.
  - Include note instructing operators to restart worker processes after saving.
- Optional: factor out shared `handleFormSubmit` logic if duplication grows, but not required.
- Keep worker/retry forms working; avoid interfering with existing event listeners.

## Test Coverage

| Criterion | Test Type | Location |
|-----------|-----------|----------|
| Runtime controls render | UI/E2E | `tests/e2e/tests/test_ui.py::test_settings_runtime_controls` |
| Runtime form submits | UI/E2E | `tests/e2e/tests/test_ui.py::test_update_runtime_config` |
| Manual QA | Docs | `docs/e2e-test-plan.md` (new checklist entry) |

## Definition of Done

- [ ] Settings template shows runtime card with load/save flows.
- [ ] Front-end requests/handles `/config` runtime payloads.
- [ ] Toast messaging informs users about restart requirement.
- [ ] Automated UI/E2E tests updated (or test plan prepared if automation deferred).
