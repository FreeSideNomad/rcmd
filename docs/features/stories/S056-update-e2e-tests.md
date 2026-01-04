# S056: Update E2E Tests for Probabilistic Behaviors

## Parent Feature

[F011 - Probabilistic Test Command Behaviors](../F011-probabilistic-test-behaviors.md)

## User Story

**As a** developer
**I want** all E2E tests updated to use probabilistic behavior configuration
**So that** tests continue to pass and demonstrate the new behavior model

## Context

Update existing E2E tests to use the new probabilistic behavior format. Tests that require deterministic outcomes should use 100% probabilities. This ensures comprehensive test coverage of the new behavior model.

## Acceptance Criteria (Given-When-Then)

### Scenario: Success scenario tests

**Given** tests in `test_success_scenarios.py`
**When** they create commands with success behavior
**Then** they use `{"fail_permanent_pct": 0, "fail_transient_pct": 0, "timeout_pct": 0}`
**Or** they use `{}` (empty behavior for defaults)

### Scenario: Permanent failure tests

**Given** tests in `test_failure_scenarios.py` for permanent failures
**When** they create commands that should fail permanently
**Then** they use `{"fail_permanent_pct": 100}`
**And** the command always raises PermanentCommandError

### Scenario: Transient failure tests

**Given** tests for transient failure behavior
**When** they create commands that should fail transiently
**Then** they use `{"fail_transient_pct": 100}`
**And** the command always raises TransientCommandError

### Scenario: Timeout tests

**Given** tests for timeout behavior
**When** they create commands that should timeout
**Then** they use `{"timeout_pct": 100}`
**And** the command sleeps longer than visibility timeout

### Scenario: TSQ operation tests

**Given** tests in `test_tsq_operations.py`
**When** they create commands for TSQ testing
**Then** they use 100% failure probabilities as needed
**And** TSQ operations work correctly

### Scenario: All E2E tests pass

**Given** all E2E tests have been updated
**When** I run `make test-e2e`
**Then** all tests pass
**And** no references to old behavior types remain

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Success tests pass | E2E | `tests/e2e/tests/test_success_scenarios.py` |
| Failure tests pass | E2E | `tests/e2e/tests/test_failure_scenarios.py` |
| TSQ tests pass | E2E | `tests/e2e/tests/test_tsq_operations.py` |

## Story Size

M (2000-4000 tokens)

## Priority (MoSCoW)

Must Have

## Dependencies

- S051 (handler logic implemented)
- S052 (API schemas updated)

## Technical Notes

### Migration Mappings

| Old Behavior | New Behavior |
|--------------|--------------|
| `{"type": "success"}` | `{}` |
| `{"type": "success", "execution_time_ms": 100}` | `{"min_duration_ms": 100, "max_duration_ms": 100}` |
| `{"type": "fail_permanent"}` | `{"fail_permanent_pct": 100}` |
| `{"type": "fail_permanent", "error_code": "X"}` | `{"fail_permanent_pct": 100, "error_code": "X"}` |
| `{"type": "fail_transient"}` | `{"fail_transient_pct": 100}` |
| `{"type": "timeout"}` | `{"timeout_pct": 100}` |
| `{"type": "fail_transient_then_succeed", "transient_failures": 2}` | See note below |

### Handling fail_transient_then_succeed

The old `fail_transient_then_succeed` behavior is not directly mappable to probabilistic mode. Tests that used this should be refactored to:

1. Use `fail_transient_pct: 100` and verify retry behavior
2. Or create multiple commands with different configurations
3. Or use 0% failure for success-after-retry verification

### Example Test Updates

```python
# Before
behavior = {"type": "success", "execution_time_ms": 100}

# After
behavior = {"min_duration_ms": 100, "max_duration_ms": 100}
```

```python
# Before
behavior = {"type": "fail_permanent", "error_code": "INVALID_DATA"}

# After
behavior = {"fail_permanent_pct": 100, "error_code": "INVALID_DATA"}
```

### Files to Update

- `tests/e2e/tests/test_success_scenarios.py`
- `tests/e2e/tests/test_failure_scenarios.py`
- `tests/e2e/tests/test_tsq_operations.py`
- `tests/e2e/tests/conftest.py` (if it has behavior fixtures)

### Verification

```bash
# Check for old behavior types
grep -r '"type":' tests/e2e/tests/
grep -r "'type':" tests/e2e/tests/

# Should return no matches after update
```

## Files to Modify

- `tests/e2e/tests/test_success_scenarios.py`
- `tests/e2e/tests/test_failure_scenarios.py`
- `tests/e2e/tests/conftest.py`

## Definition of Done

- [ ] All E2E tests updated to probabilistic format
- [ ] No references to old `type` field in tests
- [ ] Success tests use 0% failure probabilities
- [ ] Failure tests use 100% failure probabilities
- [ ] All E2E tests pass
- [ ] Test coverage maintained
