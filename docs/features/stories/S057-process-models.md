# S057: Process Manager Domain Models

## User Story

As a developer, I want typed domain models for process management so that I can build type-safe process managers with IDE autocompletion and compile-time safety.

## Acceptance Criteria

### AC1: ProcessStatus Enum
- Given process status tracking is needed
- When I use ProcessStatus enum
- Then I have: PENDING, IN_PROGRESS, WAITING_FOR_REPLY, WAITING_FOR_TSQ, COMPENSATING, COMPLETED, COMPENSATED, FAILED, CANCELED

### AC2: ProcessMetadata Dataclass
- Given a process instance is created
- When I create ProcessMetadata
- Then it contains: domain, process_id, process_type, status, current_step, state (typed), timestamps, error info

### AC3: ProcessAuditEntry Dataclass
- Given step execution needs logging
- When I create ProcessAuditEntry
- Then it contains: step_name, command_id, command_type, command_data, sent_at, reply_outcome, reply_data, received_at

### AC4: ProcessState Protocol
- Given state serialization is needed
- When I implement ProcessState protocol
- Then state class has to_dict() and from_dict() methods for JSON serialization

### AC5: ProcessCommand Dataclass
- Given command building is needed
- When I use ProcessCommand
- Then it wraps command_type and typed data with to_dict() support

### AC6: ProcessResponse Dataclass
- Given response parsing is needed
- When I use ProcessResponse.from_reply()
- Then it extracts typed result from Reply with proper deserialization

## Implementation Notes

- Location: `src/commandbus/process/models.py`
- Use Generic[TState, TStep] for typed metadata
- TStep bound to StrEnum for step names
- ProcessStatus inherits from str and Enum for JSON compatibility
- All dataclasses should have proper type hints

## Technical Notes

```python
# Type variables for generic process metadata
TState = TypeVar("TState", bound=ProcessState)
TStep = TypeVar("TStep", bound=StrEnum)

# ProcessMetadata is generic over state and step types
ProcessMetadata(Generic[TState, TStep])
```

## Verification

- [ ] All models have complete type hints
- [ ] ProcessStatus values match design doc
- [ ] ProcessMetadata fields match database schema
- [ ] to_dict/from_dict methods handle all field types
