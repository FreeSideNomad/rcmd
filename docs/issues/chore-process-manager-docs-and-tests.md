[Chore]: Document Process Manager usage and harden repository tests

## Summary
Add missing README guidance for the new Process Manager feature and ensure the process repository tests cover psycopg's `Jsonb` serialization so future regressions are caught.

## Category
Documentation

## Motivation
- README lacked any mention of how to implement or use processes even though the feature shipped, making it hard for users to adopt.
- Unit tests around `PostgresProcessRepository` failed under `make ready` because Jsonb wrappers weren't accounted for.
- We need parity between docs and code behavior ahead of e2e testing.

## Tasks
- [x] Expand README with “Process Manager” section that explains modeling steps/state, implementing `BaseProcessManager`, wiring the reply router, and starting processes (using `tests/e2e/app/process/statement_report.py` as the reference).
- [x] Keep psycopg `Jsonb` conversions in `PostgresProcessRepository` and update unit tests to assert against `Jsonb` rather than raw dicts.
- [x] Add integration coverage (`tests/integration/test_process_repository.py`) to ensure dict state/command data round-trips through Postgres JSONB columns.
- [x] Run `make ready` (format → lint → mypy → coverage + integration tests) to verify everything passes.

## Files Affected
- `README.md`
- `src/commandbus/process/repository.py`
- `tests/unit/test_process_repository.py`
- `tests/integration/test_process_repository.py`
- `.codex/CODEX.md`

## Priority
Medium

## Risks / Considerations
- Requires Docker Postgres for integration tests; ensure contributors know to run `make docker-up`.
- Documentation references e2e artifacts, so future refactors must keep code snippets in sync.

## Acceptance Criteria
- [x] README explains how to build and run processes with code snippets from the Statement Report example.
- [x] Unit and integration tests account for `Jsonb` serialization and pass via `make ready`.
- [x] CI-ready branch with failing tests fixed and docs updated.
- [x] Issue linked in commits/PR.

## LLM Agent Notes
- Reference files: `tests/e2e/app/process/statement_report.py`, `src/commandbus/process/repository.py`, `tests/unit/test_process_repository.py`.
- Ensure `make ready` is executed before committing.
