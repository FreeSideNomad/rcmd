# S059: Base Process Manager

## User Story

As a developer, I want an abstract base class for process managers so that I can implement typed process flows with minimal boilerplate.

## Acceptance Criteria

### AC1: BaseProcessManager Generic Class
- Given process type safety is needed
- When I extend BaseProcessManager[TState, TStep]
- Then I get typed state and step handling with IDE support

### AC2: Abstract Properties
- Given process identification is needed
- When I implement process_type and domain properties
- Then they return strings uniquely identifying the process type and domain

### AC3: start() Method
- Given a process needs to begin
- When I call start(initial_data)
- Then:
  1. New process_id (UUID) is generated
  2. create_initial_state() creates typed state
  3. Process is saved to repository with PENDING status
  4. get_first_step() determines first step
  5. First command is sent
  6. Returns process_id

### AC4: build_command() Abstract Method
- Given a step needs to execute
- When build_command(step, state) is called
- Then it returns ProcessCommand with typed data for that step

### AC5: update_state() Abstract Method
- Given a reply is received
- When update_state(state, step, reply) is called
- Then state is mutated in place with data extracted from reply

### AC6: get_next_step() Abstract Method
- Given current step completes
- When get_next_step(step, reply, state) is called
- Then it returns next TStep to execute or None if process is complete

### AC7: handle_reply() Method
- Given a reply arrives from command execution
- When handle_reply(reply, process) is called
- Then:
  1. Reply is recorded in audit trail
  2. update_state() is called to mutate state
  3. If reply.outcome == FAILED: handle_failure()
  4. If reply.outcome == CANCELED: run_compensations()
  5. Otherwise: get_next_step() determines continuation
  6. If next_step is None: complete process
  7. If next_step exists: execute it

### AC8: _execute_step() Internal Method
- Given a step needs to be executed
- When _execute_step(process, step) is called
- Then:
  1. build_command() creates command
  2. Command sent via command_bus with correlation_id=process_id
  3. Process status set to WAITING_FOR_REPLY
  4. Command recorded in audit trail

### AC9: get_compensation_step() Optional Method
- Given compensation is needed
- When get_compensation_step(step) is called
- Then it returns compensation step or None (default returns None)

## Implementation Notes

- Location: `src/commandbus/process/base.py`
- Commands sent with `correlation_id=process_id`, `reply_to=reply_queue`
- Status transitions handled internally
- Concrete implementations only need to implement abstract methods

## Example Implementation

```python
class StatementReportProcess(BaseProcessManager[StatementReportState, StatementReportStep]):

    @property
    def process_type(self) -> str:
        return "StatementReport"

    @property
    def domain(self) -> str:
        return "reporting"

    def create_initial_state(self, initial_data: dict) -> StatementReportState:
        return StatementReportState.from_dict(initial_data)

    def get_first_step(self, state: StatementReportState) -> StatementReportStep:
        return StatementReportStep.QUERY

    async def build_command(self, step, state) -> ProcessCommand:
        match step:
            case StatementReportStep.QUERY:
                return ProcessCommand("StatementQuery", StatementQueryRequest(...))
            # ... other steps

    def update_state(self, state, step, reply) -> None:
        match step:
            case StatementReportStep.QUERY:
                state.query_result_path = reply.data["result_path"]
            # ... other steps

    def get_next_step(self, step, reply, state) -> StatementReportStep | None:
        match step:
            case StatementReportStep.QUERY:
                return StatementReportStep.AGGREGATE
            case StatementReportStep.AGGREGATE:
                return StatementReportStep.RENDER
            case StatementReportStep.RENDER:
                return None  # Complete
```

## Verification

- [ ] Abstract methods properly defined
- [ ] start() creates and saves process correctly
- [ ] handle_reply() handles all outcome types
- [ ] Commands include correlation_id and reply_to
- [ ] Status transitions are correct
