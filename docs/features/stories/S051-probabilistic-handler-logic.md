# S051: Probabilistic Handler Logic

## Parent Feature

[F011 - Probabilistic Test Command Behaviors](../F011-probabilistic-test-behaviors.md)

## User Story

**As a** tester
**I want** test commands to evaluate failure probabilities at execution time
**So that** I can simulate realistic production workloads with stochastic failures

## Context

Replace the deterministic behavior handler with probabilistic evaluation. Each command execution rolls for failures in order: permanent failure, transient failure, timeout. If none trigger, the command succeeds with a duration sampled from a normal distribution.

## Acceptance Criteria (Given-When-Then)

### Scenario: Permanent failure probability

**Given** a test command with `fail_permanent_pct: 100`
**When** the handler processes the command
**Then** a PermanentCommandError is raised
**And** the command moves to the troubleshooting queue

### Scenario: Transient failure probability

**Given** a test command with `fail_transient_pct: 100`
**When** the handler processes the command
**Then** a TransientCommandError is raised
**And** the command is scheduled for retry

### Scenario: Timeout probability

**Given** a test command with `timeout_pct: 100`
**When** the handler processes the command
**Then** the handler sleeps longer than visibility timeout
**And** the command is eventually marked as successful

### Scenario: Success with duration

**Given** a test command with all failure probabilities at 0
**And** `min_duration_ms: 50` and `max_duration_ms: 200`
**When** the handler processes the command
**Then** the command succeeds
**And** execution takes between 50-200ms (normal distribution)

### Scenario: Sequential probability evaluation

**Given** a test command with `fail_permanent_pct: 50` and `fail_transient_pct: 50`
**When** the handler processes the command multiple times
**Then** permanent failures occur ~50% of the time
**And** transient failures occur ~25% of the time (50% of remaining 50%)
**And** successes occur ~25% of the time

### Scenario: Duration sampling follows normal distribution

**Given** 1000 test commands with `min_duration_ms: 100` and `max_duration_ms: 200`
**When** all commands are processed
**Then** the mean duration is approximately 150ms
**And** 99.7% of durations fall within [100, 200]ms

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Permanent failure at 100% | Unit | `tests/unit/test_e2e_handler.py::test_permanent_failure_100_pct` |
| Transient failure at 100% | Unit | `tests/unit/test_e2e_handler.py::test_transient_failure_100_pct` |
| Success at 0% failures | Unit | `tests/unit/test_e2e_handler.py::test_success_zero_failures` |
| Duration sampling | Unit | `tests/unit/test_e2e_handler.py::test_duration_normal_distribution` |
| Sequential evaluation | Unit | `tests/unit/test_e2e_handler.py::test_sequential_probability_evaluation` |

## Story Size

M (2000-4000 tokens)

## Priority (MoSCoW)

Must Have

## Dependencies

None (this is the foundation for F011)

## Technical Notes

### Handler Changes

Replace `tests/e2e/app/handlers.py` implementation:

```python
import random

async def handle_test_command(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
    behavior = test_cmd.behavior

    # Roll for permanent failure
    if random.random() * 100 < behavior.get("fail_permanent_pct", 0):
        raise PermanentCommandError(...)

    # Roll for transient failure
    if random.random() * 100 < behavior.get("fail_transient_pct", 0):
        raise TransientCommandError(...)

    # Roll for timeout
    if random.random() * 100 < behavior.get("timeout_pct", 0):
        await asyncio.sleep(visibility_timeout * 1.5)

    # Success with duration
    duration_ms = _sample_duration(min_ms, max_ms)
    await asyncio.sleep(duration_ms / 1000)
    return {"status": "success"}
```

### Duration Sampling

```python
def _sample_duration(min_ms: int, max_ms: int) -> float:
    if min_ms == max_ms:
        return float(min_ms)
    mean = (min_ms + max_ms) / 2
    std_dev = (max_ms - min_ms) / 6  # 99.7% within range
    sample = random.gauss(mean, std_dev)
    return max(min_ms, min(max_ms, sample))
```

## Files to Modify

- `tests/e2e/app/handlers.py` - Replace deterministic with probabilistic logic

## Definition of Done

- [ ] Handler evaluates probabilities sequentially
- [ ] Permanent failures raise PermanentCommandError
- [ ] Transient failures raise TransientCommandError
- [ ] Timeout causes sleep > visibility_timeout
- [ ] Success duration follows normal distribution
- [ ] Unit tests cover all probability scenarios
- [ ] Existing E2E tests still pass (with updated behavior configs)
