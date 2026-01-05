# F011 - Probabilistic Test Command Behaviors

## Overview

Replace the deterministic test command behavior system with a unified probabilistic model. All TestCommands are configured with probability percentages for each failure mode, enabling realistic simulation of production workloads where failures occur stochastically.

## Motivation

Production systems don't fail deterministically. Real-world conditions include:
- A percentage of commands fail permanently (validation errors, bad data)
- A percentage experience transient failures (network issues, timeouts)
- A percentage timeout (slow external services)
- Most commands succeed with varying execution times

Probabilistic behaviors enable:
1. **Realistic load testing** - Simulate production-like failure rates
2. **Chaos engineering** - Test system resilience under varying failure conditions
3. **Capacity planning** - Understand how different failure mixes affect throughput
4. **Dashboard validation** - Verify UI correctly displays mixed command outcomes

## Behavior Evaluation Model

When a command is processed, behaviors are evaluated in the following order:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Command Execution                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ Roll for        │
                    │ fail_permanent  │──Yes──► PermanentCommandError
                    │ (0-100%)        │
                    └────────┬────────┘
                             │ No
                             ▼
                    ┌─────────────────┐
                    │ Roll for        │
                    │ fail_transient  │──Yes──► TransientCommandError
                    │ (0-100%)        │
                    └────────┬────────┘
                             │ No
                             ▼
                    ┌─────────────────┐
                    │ Roll for        │
                    │ timeout         │──Yes──► Sleep(visibility_timeout * 1.5)
                    │ (0-100%)        │         then SUCCESS
                    └────────┬────────┘
                             │ No
                             ▼
                    ┌─────────────────┐
                    │ SUCCESS         │
                    │ duration =      │
                    │ normal(min,max) │
                    └─────────────────┘
```

### Evaluation Rules

1. **Sequential evaluation**: Each probability is evaluated independently in order
2. **Independent rolls**: Each check is a separate random draw (0-100)
3. **First match wins**: Once a behavior triggers, no further evaluation occurs
4. **Success is the default**: If no failure behavior triggers, command succeeds

### Probability Semantics

- `fail_permanent_pct: 5.0` means 5% chance of permanent failure
- `fail_transient_pct: 10.0` means 10% chance of transient failure (if not already permanently failed)
- `timeout_pct: 2.0` means 2% chance of timeout (if not already failed)

**Note**: Probabilities are NOT additive. With the above settings:
- 5% permanent fail
- 9.5% transient fail (10% of remaining 95%)
- ~1.7% timeout (2% of remaining 85.5%)
- ~83.8% success

### Simulating Deterministic Behaviors

The old deterministic behaviors can be achieved with specific probability settings:

| Old Behavior | Probabilistic Equivalent |
|--------------|--------------------------|
| `success` | All probabilities = 0% |
| `fail_permanent` | `fail_permanent_pct: 100` |
| `fail_transient` | `fail_transient_pct: 100` |
| `timeout` | `timeout_pct: 100` |

## Behavior JSON Schema

```json
{
  "fail_permanent_pct": 5.0,
  "fail_transient_pct": 10.0,
  "timeout_pct": 2.0,
  "min_duration_ms": 50,
  "max_duration_ms": 200,
  "error_code": "SIMULATED_ERROR",
  "error_message": "Probabilistic failure"
}
```

### Field Definitions

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `fail_permanent_pct` | float | `0.0` | Probability (0-100) of permanent failure |
| `fail_transient_pct` | float | `0.0` | Probability (0-100) of transient failure |
| `timeout_pct` | float | `0.0` | Probability (0-100) of timeout behavior |
| `min_duration_ms` | int | `0` | Minimum execution duration for success |
| `max_duration_ms` | int | `0` | Maximum execution duration for success |
| `error_code` | string | `null` | Error code for failures |
| `error_message` | string | `null` | Error message for failures |

### Duration Distribution

For successful commands, execution time follows a normal distribution:
- Mean: `(min_duration_ms + max_duration_ms) / 2`
- Standard deviation: `(max_duration_ms - min_duration_ms) / 6` (99.7% within range)
- Values are clamped to `[min_duration_ms, max_duration_ms]`

If `min_duration_ms == max_duration_ms`, that exact duration is used.
If both are 0, no artificial delay is added.

## API Changes

### Single Command Creation

```python
# POST /api/commands
{
  "behavior": {
    "fail_permanent_pct": 5.0,
    "fail_transient_pct": 10.0,
    "timeout_pct": 2.0,
    "min_duration_ms": 50,
    "max_duration_ms": 200
  },
  "payload": {}
}
```

### Bulk Command Creation

```python
# POST /api/commands/bulk
{
  "count": 1000,
  "behavior": {
    "fail_permanent_pct": 5.0,
    "fail_transient_pct": 10.0,
    "timeout_pct": 2.0,
    "min_duration_ms": 50,
    "max_duration_ms": 200
  }
}
```

All 1000 commands share the same probability configuration, but each command's actual behavior is determined at execution time by independent random rolls.

## Handler Implementation

```python
import random

@handler(domain="e2e", command_type="TestCommand")
async def handle_test_command(self, cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
    repo = TestCommandRepository(self._pool)
    attempt = await repo.increment_attempts(cmd.command_id)

    test_cmd = await repo.get_by_command_id(cmd.command_id)
    if not test_cmd:
        raise PermanentCommandError(
            code="TEST_COMMAND_NOT_FOUND",
            message=f"Test command {cmd.command_id} not found",
        )

    behavior = test_cmd.behavior

    # Roll for permanent failure
    if random.random() * 100 < behavior.get("fail_permanent_pct", 0):
        raise PermanentCommandError(
            code=behavior.get("error_code", "PERMANENT_ERROR"),
            message=behavior.get("error_message", "Probabilistic permanent failure")
        )

    # Roll for transient failure
    if random.random() * 100 < behavior.get("fail_transient_pct", 0):
        raise TransientCommandError(
            code=behavior.get("error_code", "TRANSIENT_ERROR"),
            message=behavior.get("error_message", "Probabilistic transient failure")
        )

    # Roll for timeout
    if random.random() * 100 < behavior.get("timeout_pct", 0):
        # Sleep longer than visibility timeout to trigger redelivery
        visibility_timeout = 30  # Could be from config
        await asyncio.sleep(visibility_timeout * 1.5)

    # Success path - calculate duration
    min_ms = behavior.get("min_duration_ms", 0)
    max_ms = behavior.get("max_duration_ms", 0)

    if min_ms > 0 or max_ms > 0:
        duration_ms = _sample_duration(min_ms, max_ms)
        await asyncio.sleep(duration_ms / 1000)

    result = {"status": "success", "attempt": attempt}
    await repo.mark_processed(cmd.command_id, result)
    return result

def _sample_duration(min_ms: int, max_ms: int) -> float:
    """Sample duration from normal distribution, clamped to [min, max]."""
    if min_ms == max_ms:
        return float(min_ms)

    mean = (min_ms + max_ms) / 2
    # 6 sigma covers 99.7% of values
    std_dev = (max_ms - min_ms) / 6

    sample = random.gauss(mean, std_dev)
    return max(min_ms, min(max_ms, sample))
```

## UI Changes

### Single Command Form

Replace behavior type dropdown with probability inputs:

```
┌─────────────────────────────────────────────────────────────────┐
│  Send Command                                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Failure Probabilities                                   │    │
│  ├─────────────────────────────────────────────────────────┤    │
│  │ Permanent Failure:  [====░░░░░░░░░░░░░░░░]  5.0%        │    │
│  │ Transient Failure:  [========░░░░░░░░░░░░]  10.0%       │    │
│  │ Timeout:            [==░░░░░░░░░░░░░░░░░░]  2.0%        │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Success Duration (ms)                                   │    │
│  ├─────────────────────────────────────────────────────────┤    │
│  │ Min: [  50  ]    Max: [  200  ]                         │    │
│  │                                                         │    │
│  │ Distribution: Normal (mean=125ms, 99.7% in range)       │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  Expected Outcomes (per 1000 commands):                         │
│  • ~50 permanent failures                                       │
│  • ~95 transient failures                                       │
│  • ~17 timeouts                                                 │
│  • ~838 successes                                               │
│                                                                 │
│                                      [ Send Command ]           │
└─────────────────────────────────────────────────────────────────┘
```

### Bulk Command Form

Same probability configuration section:

```
┌─────────────────────────────────────────────────────────────────┐
│  Bulk Create Commands                                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Count: [ 10000 ]                                               │
│                                                                 │
│  Failure Probabilities:                                         │
│  ├── Permanent: [  5.0  ] %                                     │
│  ├── Transient: [ 10.0  ] %                                     │
│  └── Timeout:   [  2.0  ] %                                     │
│                                                                 │
│  Duration Range:                                                │
│  ├── Min: [  50  ] ms                                           │
│  └── Max: [ 200  ] ms                                           │
│                                                                 │
│  Expected Distribution:                                         │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ ████████████████████████████████████████ Success: 8380 │     │
│  │ ████                                    Permanent: 500 │     │
│  │ ████████                                Transient: 950 │     │
│  │ ██                                      Timeout: 170   │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                 │
│                                    [ Create 10,000 Commands ]   │
└─────────────────────────────────────────────────────────────────┘
```

## Migration from Deterministic Behaviors

The old deterministic behavior types are removed. Existing E2E tests must be updated to use probabilistic configuration:

| Old Test Setup | New Test Setup |
|----------------|----------------|
| `{"type": "success"}` | `{"fail_permanent_pct": 0, "fail_transient_pct": 0, "timeout_pct": 0}` or `{}` |
| `{"type": "fail_permanent"}` | `{"fail_permanent_pct": 100}` |
| `{"type": "fail_transient"}` | `{"fail_transient_pct": 100}` |
| `{"type": "fail_transient_then_succeed", "transient_failures": 2}` | N/A - use `fail_transient_pct: 100` and verify retry behavior |
| `{"type": "timeout"}` | `{"timeout_pct": 100}` |

## Implementation Stories

| Story | Description | Priority |
|-------|-------------|----------|
| S051 | Replace handler with probabilistic behavior logic | Must Have |
| S052 | Update API schemas (remove type, add probability fields) | Must Have |
| S053 | Update single command UI with probability sliders | Must Have |
| S054 | Update bulk command UI with probability inputs | Must Have |
| S055 | Add expected outcome calculator in UI | Should Have |
| S056 | Update E2E tests to use probabilistic behaviors | Must Have |

## Success Criteria

1. All TestCommands use probabilistic behavior configuration
2. Single commands can be created with probability settings via UI
3. Bulk commands apply probabilistic behaviors independently per command
4. Actual outcome distribution matches expected probabilities within statistical tolerance
5. UI provides intuitive probability configuration with visual feedback
6. All E2E tests updated and passing

## Testing Strategy

### Unit Tests

- Probability evaluation logic with mocked random
- Duration sampling distribution validation
- Schema validation for probabilistic fields

### Integration Tests

- Create 1000 commands with 50% transient failure rate
- Verify ~500 end up in TSQ after retries exhausted
- Verify ~500 complete successfully

### Statistical Validation

For large batches (N=10000), verify:
- Actual permanent failures within 2 standard deviations of expected
- Chi-squared test for uniform random distribution
