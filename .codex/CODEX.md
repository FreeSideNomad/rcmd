# Codex Knowledge Base

Reference guide for Codex agents working in the `rcmd` repository.

## Repository Snapshot
- Library name: `reliable-cmd` (Python 3.11+) providing a durable Command Bus over PostgreSQL + PGMQ (`README.md`).
- Core package lives under `src/commandbus/` with bus, worker, handler registry, policies, repositories, and a PGMQ client wrapper.
- Tooling: `make install|lint|format|typecheck|test|test-unit|test-integration|coverage`. Use `make ready` (format → lint → typecheck → coverage) before every commit.
- Tests live in `tests/unit`, `tests/integration`, and `tests/e2e`. Coverage threshold is 80% line & branch; enforced via pre-commit (`.claude/CLAUDE.md`).

## Process Manager Feature (F013)
- Feature implemented per `docs/process-manager-design.md` and `docs/features/F013-process-manager.md`.
- Provides process metadata/audit tables, typed state, reply-driven progression, TSQ integration, and e2e StatementReportProcess scenario.
- Current focus: troubleshooting e2e tests for the process manager feature; exploratory testing is surfacing defects that must follow the bug workflow below.

## Workflow Rules
1. **Issue first** – create GitHub issue via `.github/ISSUE_TEMPLATE/03-bug.yml` for defects (see `.claude/CLAUDE.md`).
2. **Feature branch** – branch from main using `feat/`, `fix/`, `chore/`, or `docs/` prefixes referencing the issue number (e.g., `fix/123-process-manager-tsq`).
3. **Run `make ready`** before committing; ensure formatting, lint, mypy, and coverage pass locally.
4. **Commit format** – `<type>: <description>` with `Closes #<issue>` footer, plus the provided Claude attribution block.
5. **Pull Request** – push feature branch, open PR, and wait for human review; never push to `main`.
6. **CI monitoring** – after each push, watch GitHub Actions (`gh run list/watch`). Fix failures immediately; after 10 failed attempts escalate to a human with analysis.

## Agent Resources
- `.claude/CLAUDE.md` – master workflow + tooling requirements.
- `agent_docs/` – progressive-disclosure docs (code patterns, testing guide, database operations, common pitfalls).
- Process-related docs under `docs/` (feature specs, ADRs, E2E plans).

## Current Testing Priority
- Exploratory e2e testing for process manager workflows (StatementReportProcess UI + reply routing). Capture defects via the bug template, create fix branches, and ensure coverage + CI before PRs.
