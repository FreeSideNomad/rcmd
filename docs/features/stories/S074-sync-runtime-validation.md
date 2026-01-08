# S074: Dual-Runtime Validation & Documentation

## Parent Feature

[F014 - Synchronous Wrappers & Runtime Toggle](../F014-sync-wrapper.md)

## User Story

**As a** maintainer preparing the synchronous release
**I want** automated and manual validation across both runtimes
**So that** regressions are caught and guidance exists for QA teams.

## Context

After implementing sync wrappers, config plumbing, UI, runtime manager, and worker orchestration, we need a dedicated validation sweep. This includes expanding automated tests to cover both paths and capturing manual checklists for operators. Without this story, regressions in either runtime mode could slip through.

## Acceptance Criteria

### Scenario: Automated tests cover both runtimes
**Given** I run `make test`
**When** the suite executes
**Then** it includes unit/integration tests for sync runtime components, config endpoints, runtime manager, and worker CLI (mocked)
**And** failures clearly indicate which runtime path broke.

### Scenario: Integration smoke for sync mode
**Given** the new `tests/integration/test_sync_mode.py`
**When** it runs
**Then** it launches `SyncCommandBus` + `SyncWorker` end-to-end against a test database, proving parity with async mode.

### Scenario: Manual QA checklist documented
**Given** I open `docs/e2e-test-plan.md` (or similar)
**When** I review runtime-related tests
**Then** I see explicit steps for toggling runtime, restarting workers, sending commands, inspecting TSQ, and switching back.

### Scenario: Release notes updated
**Given** we publish the feature
**When** developers read README/release notes
**Then** they understand the new sync wrappers, env vars, and runtime toggle process.

## Technical Notes

- Testing:
  - Add/extend tests introduced in earlier stories and ensure they run in CI (update `pyproject.toml`, `Makefile`, or `pytest.ini` if new directories added).
  - Consider parametrizing fixtures so both async and sync implementations share behavioral assertions.
- Documentation:
  - Update `README.md` “Synchronous Usage” and E2E instructions.
  - Add runtime toggle steps to `docs/e2e-test-plan.md` plus any operator runbooks.
  - Mention `COMMAND_BUS_SYNC_THREADS` and `commandbus.sync.configure()` usage.
- Release communication:
  - Update relevant changelog/ADR notes describing user impact and migration guidance.

## Test Coverage

| Criterion | Test Type | Location |
|-----------|-----------|----------|
| Sync runtime smoke | Integration | `tests/integration/test_sync_mode.py` |
| FastAPI runtime manager | Integration | `tests/e2e/tests/test_api.py::test_runtime_toggle_processing` |
| Worker CLI branching | Unit | `tests/unit/test_worker_cli.py` |
| UI toggle flows | E2E | `tests/e2e/tests/test_ui.py::test_settings_runtime_controls` |

## Definition of Done

- [ ] All new automated tests added to CI and passing.
- [ ] Manual QA instructions documented for runtime toggling.
- [ ] README/release notes mention synchronous mode usage and troubleshooting tips.
- [ ] Stakeholders sign off on parity between async and sync code paths.
