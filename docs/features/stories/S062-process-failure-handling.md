# S062: Process Failure and TSQ Integration

## User Story

As a system operator, I want processes to handle failures gracefully and integrate with the Troubleshooting Queue so that I can resolve issues and optionally trigger compensation.

## Acceptance Criteria

### AC1: Failed Reply Handling
- Given a command returns FAILED outcome
- When handle_reply processes it
- Then process status is set to FAILED with error_code and error_message

### AC2: TSQ Integration
- Given a command is moved to TSQ (retries exhausted or permanent failure)
- When the process receives this information
- Then process status is set to WAITING_FOR_TSQ

### AC3: TSQ Complete Resolution
- Given an operator completes a command in TSQ
- When the SUCCESS reply reaches the process
- Then process continues to next step normally

### AC4: TSQ Cancel Resolution
- Given an operator cancels a command in TSQ
- When the CANCELED reply reaches the process
- Then process runs compensation for completed steps

### AC5: Compensation Flow
- Given a process needs compensation
- When _run_compensations() is called
- Then:
  1. Get completed steps from audit trail
  2. For each step in reverse order
  3. Call get_compensation_step(step)
  4. If compensation exists, execute it
  5. Set final status to COMPENSATED

### AC6: No Compensation Defined
- Given get_compensation_step returns None for a step
- When compensation runs
- Then that step is skipped (no compensation needed)

### AC7: Compensation Failure
- Given a compensation command fails
- When error is caught
- Then it's logged but compensation continues for remaining steps

## Implementation Notes

- Location: Failure handling in `src/commandbus/process/base.py`
- TSQ sends CANCELED reply when operator cancels
- Compensation is best-effort (failures logged, not fatal)

## Status Transitions

```
WAITING_FOR_REPLY
    │
    ├─ SUCCESS reply ─────────────────┬─> next step or COMPLETED
    │                                 │
    ├─ FAILED reply ──────────────────┴─> FAILED (terminal)
    │
    └─ (command to TSQ) ────────────────> WAITING_FOR_TSQ
                                              │
                   ┌──────────────────────────┴──────────────────────────┐
                   │                                                     │
            TSQ Complete                                           TSQ Cancel
                   │                                                     │
                   ▼                                                     ▼
        SUCCESS reply arrives                                  CANCELED reply arrives
                   │                                                     │
                   ▼                                                     ▼
           Continue process                                    COMPENSATING
                                                                        │
                                                                        ▼
                                                                   COMPENSATED
```

## Compensation Example

```python
def get_compensation_step(self, step: StatementReportStep) -> StatementReportStep | None:
    """Return compensation step for given step."""
    match step:
        case StatementReportStep.QUERY:
            return None  # Query has no side effects, no compensation
        case StatementReportStep.AGGREGATE:
            return None  # Aggregation has no side effects
        case StatementReportStep.RENDER:
            return StatementReportStep.DELETE_RENDER  # Clean up rendered file
```

## Verification

- [ ] FAILED reply sets process to FAILED status
- [ ] WAITING_FOR_TSQ status set when command goes to TSQ
- [ ] TSQ complete allows process to continue
- [ ] TSQ cancel triggers compensation
- [ ] Compensation runs in reverse order
- [ ] Missing compensations are skipped
