# Contributing to Command Bus

Thank you for your interest in contributing to Command Bus! We welcome contributions of all kinds, from bug reports to feature implementations.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Style Guidelines](#style-guidelines)
- [Getting Help](#getting-help)

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment. Be kind, constructive, and professional in all interactions.

## Getting Started

### Types of Contributions

We appreciate many types of contributions:

- **Bug Reports**: Found something broken? Open an issue with reproduction steps
- **Feature Requests**: Have an idea? Open an issue to discuss it first
- **Documentation**: Improvements to docs, examples, or code comments
- **Bug Fixes**: Fix issues and submit a pull request
- **New Features**: Implement features after discussion in an issue
- **Tests**: Improve test coverage or add missing test cases

### Before You Start

1. **Check existing issues** to avoid duplicates
2. **Open an issue first** for significant changes to discuss the approach
3. **Small PRs are better** - break large changes into smaller pieces

## Development Setup

### Prerequisites

- Python 3.11 or higher
- Docker and Docker Compose (for integration tests)
- [uv](https://docs.astral.sh/uv/) package manager

### Initial Setup

```bash
# Clone the repository
git clone https://github.com/your-org/commandbus.git
cd commandbus

# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
make install

# Verify setup
make lint
make typecheck
make test-unit
```

### Running Services

For integration tests, you'll need PostgreSQL with the PGMQ extension:

```bash
# Start services
make docker-up

# Run integration tests
make test-integration

# Stop services
make docker-down
```

## Making Changes

### Branch Naming

Use descriptive branch names:

```
feature/add-retry-backoff
fix/handle-connection-timeout
docs/update-api-reference
refactor/extract-handler-registry
```

### Commit Messages

Write clear, concise commit messages:

```
Add exponential backoff to retry policy

- Implement configurable backoff multiplier
- Add max_delay cap to prevent excessive waits
- Update tests for new behavior

Closes #42
```

Guidelines:
- Use imperative mood ("Add" not "Added")
- First line: 50 characters or less
- Blank line before detailed description
- Reference issues with "Closes #N" or "Related to #N"

### Code Changes

1. **Write tests first** when possible (TDD)
2. **Keep changes focused** - one logical change per PR
3. **Update documentation** for any API changes
4. **Add type hints** to all new functions
5. **Run the full test suite** before submitting

## Testing

### Running Tests

```bash
# All tests
make test

# Unit tests only (fast, no Docker)
make test-unit

# Integration tests (requires Docker)
make test-integration

# With coverage report
make coverage

# Specific test file
pytest tests/unit/test_api.py -v

# Specific test
pytest tests/unit/test_api.py::test_send_command -v
```

### Writing Tests

- **Unit tests**: No external dependencies, use fakes from `commandbus.testing.fakes`
- **Integration tests**: Mark with `@pytest.mark.integration`
- **Test naming**: `test_<method>_<scenario>_<expected>`

Example:

```python
@pytest.mark.asyncio
async def test_send_with_duplicate_id_raises_error(
    command_bus: CommandBus,
) -> None:
    """Sending a command with an existing ID should raise DuplicateCommandError."""
    command_id = uuid4()

    await command_bus.send(
        domain="payments",
        command_type="Debit",
        command_id=command_id,
        data={"amount": 100},
    )

    with pytest.raises(DuplicateCommandError):
        await command_bus.send(
            domain="payments",
            command_type="Debit",
            command_id=command_id,
            data={"amount": 200},
        )
```

### Coverage Requirements

- Minimum 80% overall coverage
- New code should have >90% coverage
- All public APIs must have tests

## Submitting Changes

### Pull Request Process

1. **Create a feature branch** from `main`
2. **Make your changes** following the guidelines
3. **Run all checks** locally:
   ```bash
   make lint
   make typecheck
   make test
   ```
4. **Push your branch** and open a PR
5. **Fill out the PR template** completely
6. **Address review feedback** promptly

### PR Checklist

Before requesting review:

- [ ] Tests added/updated and passing
- [ ] Linting passes (`make lint`)
- [ ] Type checking passes (`make typecheck`)
- [ ] Documentation updated if needed
- [ ] PR description explains the "why"
- [ ] Linked to related issue(s)

### Review Process

1. At least one maintainer must approve
2. All CI checks must pass
3. Conflicts must be resolved
4. Squash merge is preferred for cleaner history

## Style Guidelines

### Python Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) with 100 char line limit
- Use [ruff](https://docs.astral.sh/ruff/) for linting and formatting
- Type hints required on all public functions
- Google-style docstrings for public APIs

### Docstring Example

```python
async def send(
    self,
    domain: str,
    command_type: str,
    command_id: UUID,
    data: dict[str, Any],
) -> UUID:
    """Send a command to the specified domain queue.

    Args:
        domain: The domain name (e.g., "payments")
        command_type: The command type (e.g., "DebitAccount")
        command_id: Client-supplied idempotency key
        data: Command payload data

    Returns:
        The command_id for correlation

    Raises:
        DuplicateCommandError: If command_id already exists
        ConnectionError: If database is unavailable
    """
```

### Automated Formatting

```bash
# Format code
make format

# Check without modifying
make lint
```

## Getting Help

- **Questions**: Open a [Discussion](https://github.com/your-org/commandbus/discussions)
- **Bugs**: Open an [Issue](https://github.com/your-org/commandbus/issues)
- **Security**: Email security@your-org.com (do not open public issues)

## Recognition

Contributors are recognized in:
- The [CHANGELOG](CHANGELOG.md) for their contributions
- The GitHub contributors page

Thank you for contributing!
