# Command Bus Python Library

A Python library providing Command Bus abstraction over PostgreSQL + PGMQ.

## Quick Reference

```bash
# Development
make install          # Install dependencies with uv
make lint             # Run ruff linter
make format           # Format code with ruff
make typecheck        # Run mypy type checking
make test             # Run all tests
make test-unit        # Run unit tests only
make test-integration # Run integration tests (requires Docker)
make coverage         # Run tests with coverage report

# Docker
make docker-up        # Start Postgres + PGMQ
make docker-down      # Stop containers
```

## Tech Stack

- Python 3.11+
- PostgreSQL 15+ with PGMQ extension
- psycopg3 (async support)
- pytest + pytest-asyncio
- ruff (linting/formatting)
- mypy (type checking)
- uv (package management)

## Project Structure

```
src/commandbus/
  api.py              # Public CommandBus interface
  models.py           # Domain models (Command, Reply, etc.)
  exceptions.py       # TransientCommandError, PermanentCommandError
  policies.py         # Retry policies and backoff
  handler.py          # Handler registry
  worker.py           # Worker loop with concurrency
  repositories/
    base.py           # Repository protocols
    postgres.py       # PostgreSQL implementation
  pgmq/
    client.py         # PGMQ SQL wrapper
    notify.py         # pg_notify/LISTEN implementation
  ops/
    troubleshooting.py # Operator APIs
  testing/
    fakes.py          # FakePgmqClient for unit tests

tests/
  unit/               # No external dependencies
  integration/        # Requires Postgres + PGMQ
  e2e/                # Full system tests
```

## Code Patterns

### Error Handling

Use custom exceptions for command failures:

```python
# Permanent failure - goes to troubleshooting immediately
raise PermanentCommandError(code="INVALID_ACCOUNT", message="Account not found")

# Transient failure - retried according to policy
raise TransientCommandError(code="TIMEOUT", message="Database timeout")
```

### Repository Pattern

All data access through repository protocols:

```python
class CommandRepository(Protocol):
    async def save(self, command: CommandMetadata) -> None: ...
    async def get_by_id(self, domain: str, command_id: UUID) -> CommandMetadata | None: ...
```

### Transactions

Use context managers for transactional operations:

```python
async with self.pool.connection() as conn:
    async with conn.transaction():
        await self.repo.save(command, conn=conn)
        await self.pgmq.send(queue, payload, conn=conn)
```

## Testing Requirements

- Unit tests: No Postgres, use `FakePgmqClient` from `testing/fakes.py`
- Integration tests: Use `@pytest.mark.integration` marker
- All public methods must have type hints

### Coverage Requirements (MANDATORY)

**80% line and branch coverage is required for ALL commits.**

This is enforced via pre-commit hook. Commits will be **rejected** if coverage falls below 80%.

```bash
# Check coverage before committing
make test-coverage

# View detailed coverage report
make coverage-html
```

If coverage drops below 80%:
1. Write additional tests to cover uncovered code paths
2. Focus on branch coverage (if/else, try/except paths)
3. Do NOT reduce coverage threshold - add tests instead
4. Report to user if unable to achieve 80% coverage

## Key Files Reference

| Purpose | File |
|---------|------|
| Public API | `src/commandbus/api.py` |
| Domain models | `src/commandbus/models.py` |
| Error types | `src/commandbus/exceptions.py` |
| PGMQ wrapper | `src/commandbus/pgmq/client.py` |
| Test fakes | `src/commandbus/testing/fakes.py` |
| Migrations | `src/commandbus/migrations/` |

## Anti-Patterns to Avoid

- No global state or module-level singletons
- No `print()` statements - use `logging`
- No bare `except:` clauses - catch specific exceptions
- No magic numbers - use named constants
- No mutable default arguments

## Git Workflow Rules (MANDATORY)

These rules MUST be followed for all code changes:

### 1. Issue First

**ALWAYS create a GitHub issue before starting work.**

- **Feature/User Story**: Use `[Feature]` or `[Story]` template for new functionality
- **Bug**: Use `[Bug]` template for defects
- **Chore**: Use `[Chore]` template for everything else:
  - Dependency updates
  - CI/CD changes
  - Tooling configuration
  - Documentation updates
  - Refactoring
  - Performance improvements

When in doubt, create a **Chore** issue.

### 2. Feature Branch Required

**NEVER commit directly to `main`.**

```bash
# Create feature branch from issue number
git checkout -b <type>/<issue-number>-<short-description>

# Examples:
git checkout -b feat/23-add-retry-policy
git checkout -b fix/45-handle-null-payload
git checkout -b chore/67-update-dependencies
```

Branch naming convention:
- `feat/` - New features or user stories
- `fix/` - Bug fixes
- `chore/` - Maintenance, docs, refactoring, CI/CD
- `docs/` - Documentation only

### 3. Reference Issue in Commits

**EVERY commit MUST reference a GitHub issue.**

```bash
# Commit message format
<type>: <description>

<optional body>

Closes #<issue-number>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

Commit types:
- `feat:` - New feature
- `fix:` - Bug fix
- `chore:` - Maintenance task
- `docs:` - Documentation
- `refactor:` - Code restructuring
- `test:` - Adding tests
- `ci:` - CI/CD changes

### 4. Pull Request Required

**NEVER push directly to `main`. Always create a PR.**

```bash
# Push feature branch
git push -u origin <branch-name>

# Create PR
gh pr create --title "<type>: <description>" --body "Closes #<issue>"
```

**Human review is REQUIRED before merge.** Do not merge PRs autonomously.

### 5. Monitor GitHub Actions (MANDATORY)

**ALWAYS check GitHub Actions after pushing commits.**

```bash
# Check CI status after push
gh run list --limit 5
gh run watch  # Watch current run

# View failed run details
gh run view <run-id> --log-failed
```

**CI Monitoring Rules:**

1. After every push, check GitHub Actions status
2. If CI fails, analyze the error and push a fix
3. Repeat until CI passes or **10 commits reached**
4. After 10 failed attempts, **STOP and escalate to human**

```
Push → Check CI → Failed? → Fix → Push → Check CI → ...
                    ↓
            (max 10 attempts)
                    ↓
         Escalate to Human
```

**When escalating to human:**
- Comment on the PR with the CI failure details
- List all attempted fixes
- Provide analysis of the root cause
- Wait for human guidance

### 6. Workflow Summary

```
1. Create Issue (Feature/Bug/Chore)
         ↓
2. Create Feature Branch (feat/fix/chore)
         ↓
3. Make Changes + Write Tests
         ↓
4. Commit with Issue Reference
         ↓
5. Push Branch + Create PR
         ↓
6. Monitor GitHub Actions
         ↓
   ┌─── CI Passed? ───┐
   │                  │
  YES                 NO
   │                  │
   ↓                  ↓
7. Human         Fix & Push
   Reviews       (max 10x)
   & Merges          │
                     ↓
              Still failing?
                     │
                     ↓
              Escalate to Human
```

### Example Workflow

```bash
# 1. Issue exists: #42 - Add retry backoff configuration

# 2. Create branch
git checkout -b feat/42-retry-backoff-config

# 3. Make changes, ensure tests pass
make test-coverage

# 4. Commit with issue reference
git add .
git commit -m "feat: Add configurable retry backoff

Implement RetryPolicy with customizable backoff schedule.

Closes #42

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# 5. Push and create PR
git push -u origin feat/42-retry-backoff-config
gh pr create --title "feat: Add configurable retry backoff" --body "Closes #42"

# 6. Monitor GitHub Actions
gh run watch

# If CI fails, fix and push again (repeat up to 10 times)
# After 10 failures, comment on PR and wait for human

# 7. Wait for human to review and merge
```

## Verification Checklist

**BEFORE EVERY COMMIT - Run this command:**

```bash
make ready
```

This single command runs: format → lint → typecheck → test-coverage

If `make ready` fails, fix the issues before committing.

**AFTER EVERY PUSH - Check GitHub Actions:**

```bash
gh run list --limit 3   # Check status
gh run watch            # Or watch in real-time
```

If CI fails, run `gh run view <id> --log-failed` to see the error, fix it, and push again.

### Full Checklist

1. ✅ `make ready` passes (runs format, lint, typecheck, tests with 80% coverage)
2. ✅ Issue exists and is referenced in commit
3. ✅ PR created (not pushed to main directly)
4. ✅ GitHub Actions passes (check with `gh run list` after push)
5. ✅ Wait for human review before merge
