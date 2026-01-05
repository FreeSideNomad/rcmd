# S052: Probabilistic API Schemas

## Parent Feature

[F011 - Probabilistic Test Command Behaviors](../F011-probabilistic-test-behaviors.md)

## User Story

**As a** developer
**I want** the API schemas to accept probabilistic behavior configuration
**So that** I can create test commands with failure probabilities via the REST API

## Context

Update the Pydantic schemas in `tests/e2e/app/api/schemas.py` to replace the deterministic `type` field with probabilistic fields. This enables both single and bulk command creation with probability-based behavior configuration.

## Acceptance Criteria (Given-When-Then)

### Scenario: Single command with probabilities

**Given** the API endpoint `POST /api/commands`
**When** I send a request with:
```json
{
  "behavior": {
    "fail_permanent_pct": 5.0,
    "fail_transient_pct": 10.0,
    "timeout_pct": 2.0,
    "min_duration_ms": 50,
    "max_duration_ms": 200
  }
}
```
**Then** the command is created successfully
**And** the behavior is stored with probabilistic fields

### Scenario: Default probabilities

**Given** the API endpoint `POST /api/commands`
**When** I send a request with `{"behavior": {}}`
**Then** all probability fields default to 0.0
**And** duration fields default to 0
**And** the command always succeeds immediately

### Scenario: Probability validation

**Given** the API endpoint `POST /api/commands`
**When** I send a request with `fail_permanent_pct: 150`
**Then** validation fails
**And** an error message indicates the value must be 0-100

### Scenario: Bulk command with probabilities

**Given** the API endpoint `POST /api/commands/bulk`
**When** I send a request with:
```json
{
  "count": 100,
  "behavior": {
    "fail_permanent_pct": 5.0,
    "fail_transient_pct": 10.0
  }
}
```
**Then** 100 commands are created
**And** each has the same probabilistic behavior configuration

### Scenario: Remove old type field

**Given** the API endpoint `POST /api/commands`
**When** I send a request with `{"behavior": {"type": "success"}}`
**Then** the request is rejected or the `type` field is ignored

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Schema accepts probabilities | Unit | `tests/unit/test_api_schemas.py::test_behavior_probabilities` |
| Default values | Unit | `tests/unit/test_api_schemas.py::test_behavior_defaults` |
| Validation 0-100 | Unit | `tests/unit/test_api_schemas.py::test_probability_validation` |
| Bulk with probabilities | Integration | `tests/e2e/tests/test_api.py::test_bulk_probabilistic` |

## Story Size

S (1000-2000 tokens)

## Priority (MoSCoW)

Must Have

## Dependencies

- S051 (handler must understand new behavior format)

## Technical Notes

### Schema Changes

```python
# tests/e2e/app/api/schemas.py

class CommandBehavior(BaseModel):
    """Probabilistic test command behavior specification."""

    fail_permanent_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Probability (0-100) of permanent failure"
    )
    fail_transient_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Probability (0-100) of transient failure"
    )
    timeout_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Probability (0-100) of timeout"
    )
    min_duration_ms: int = Field(
        default=0,
        ge=0,
        description="Minimum execution duration in ms"
    )
    max_duration_ms: int = Field(
        default=0,
        ge=0,
        description="Maximum execution duration in ms"
    )
    error_code: str | None = Field(
        default=None,
        description="Error code for failures"
    )
    error_message: str | None = Field(
        default=None,
        description="Error message for failures"
    )
```

### Remove Old Fields

Remove from `CommandBehavior`:
- `type` field
- `transient_failures` field
- `execution_time_ms` field (replaced by min/max duration)

### Update BulkCreateRequest

Remove `behavior_distribution` since probabilistic mode replaces the distribution concept.

## Files to Modify

- `tests/e2e/app/api/schemas.py` - Update CommandBehavior schema
- `tests/e2e/app/api/routes.py` - Remove behavior distribution logic

## Definition of Done

- [ ] CommandBehavior schema has probabilistic fields
- [ ] Old `type` field removed
- [ ] Probability validation (0-100) enforced
- [ ] Duration validation (>= 0) enforced
- [ ] Default values are all 0 (immediate success)
- [ ] Bulk endpoint accepts probabilistic behaviors
- [ ] API documentation updated
