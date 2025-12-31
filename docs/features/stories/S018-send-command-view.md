# S018 - Send Command View

## Parent Feature
F006 - E2E Testing & Demo Application

## User Story

**As a** tester/operator
**I want** a UI to send test commands with configurable behaviors
**So that** I can test various command scenarios and generate load

## Context

This view allows users to create test commands with specific behavior configurations. It supports both single command creation and bulk generation for load testing.

## Acceptance Criteria

### Scenario: Send single command with success behavior
**Given** I am on the Send Command page
**When** I select behavior type "success"
**And** I click "Send Command"
**Then** a new command is created with status PENDING
**And** a success message shows the command_id
**And** the test_command table has the behavior stored

### Scenario: Send command with transient-then-succeed behavior
**Given** I am on the Send Command page
**When** I select behavior type "fail_transient_then_succeed"
**And** I set transient_failures to 3
**And** I click "Send Command"
**Then** the command is created with behavior `{"type": "fail_transient_then_succeed", "transient_failures": 3}`

### Scenario: Send command with permanent failure behavior
**Given** I am on the Send Command page
**When** I select behavior type "fail_permanent"
**And** I set error_code to "INVALID_ACCOUNT"
**And** I set error_message to "Account not found"
**And** I click "Send Command"
**Then** the command is created with the specified error details

### Scenario: Bulk command generation
**Given** I am on the Send Command page
**When** I set count to 100
**And** I select behavior type "success"
**And** I click "Generate Bulk"
**Then** 100 commands are created
**And** a summary shows "100 commands created"

### Scenario: Configure execution time
**Given** I am on the Send Command page
**When** I set execution_time_ms to 500
**And** I click "Send Command"
**Then** the behavior includes `"execution_time_ms": 500`
**And** the command will take ~500ms to execute

### Scenario: Configure max_attempts per command
**Given** I am on the Send Command page
**When** I set max_attempts to 5
**And** I click "Send Command"
**Then** the command is created with max_attempts=5
**And** it can retry up to 5 times before TSQ

## UI Design

### Form Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| Behavior Type | Select | Yes | success, fail_permanent, fail_transient, fail_transient_then_succeed, timeout |
| Transient Failures | Number | No | How many transient failures before success |
| Error Code | Text | No | Error code for failure behaviors |
| Error Message | Text | No | Error message for failure behaviors |
| Execution Time (ms) | Number | No | How long command execution takes (simulates real work) |
| Max Attempts | Number | No | Override default max_attempts for this command |
| Custom Payload | JSON | No | Additional payload data |
| Count | Number | No | For bulk generation (default 1) |

### Current Configuration Display

The form shows current worker/retry configuration (read from settings):

```
┌─ Current Configuration (editable in Settings) ─────────────────────────────┐
│ Visibility Timeout: 30s │ Max Attempts: 3 │ Backoff: 1s-60s (2x multiplier)│
└─────────────────────────────────────────────────────────────────────────────┘
```

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│ Send Test Command                                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─ Current Configuration (edit in Settings) ─────────────┐ │
│  │ Visibility: 30s │ Max Attempts: 3 │ Backoff: 1s-60s    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  Behavior Type: [success ▼]                                  │
│                                                              │
│  ┌─ Failure Settings (shown when applicable) ─────────────┐ │
│  │ Transient Failures: [___]                               │ │
│  │ Error Code: [________________]                          │ │
│  │ Error Message: [________________]                       │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ Execution Settings ─────────────────────────────────────┐ │
│  │ Execution Time (ms): [___]  Max Attempts: [3__]         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ Payload (optional) ─────────────────────────────────────┐ │
│  │ { "custom": "data" }                                    │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─ Bulk Generation ────────────────────────────────────────┐ │
│  │ Count: [1___]  [Generate Bulk]                          │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  [Send Single Command]                                       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## API Endpoints

### POST /api/v1/commands
Create a single test command.

**Request:**
```json
{
  "behavior": {
    "type": "fail_transient_then_succeed",
    "transient_failures": 2,
    "delay_ms": 100
  },
  "payload": {"custom": "data"}
}
```

**Response:**
```json
{
  "command_id": "uuid",
  "status": "PENDING",
  "msg_id": 123
}
```

### POST /api/v1/commands/bulk
Generate multiple test commands.

**Request:**
```json
{
  "count": 100,
  "behavior": {
    "type": "success",
    "delay_ms": 50
  }
}
```

**Response:**
```json
{
  "created": 100,
  "command_ids": ["uuid1", "uuid2", ...]
}
```

## Files to Create/Modify

- `tests/e2e/app/api/routes.py` - Add POST /commands and /commands/bulk
- `tests/e2e/app/templates/pages/send_command.html`
- `tests/e2e/app/static/js/send_command.js`

## Definition of Done

- [ ] Send Command page accessible from sidebar
- [ ] All behavior types configurable via form
- [ ] Single command creation works
- [ ] Bulk command generation works
- [ ] Form validation for required fields
- [ ] Success/error feedback to user
- [ ] API endpoints implemented and tested

## Story Size
M (2000-5000 tokens)

## Priority
Must Have

## Dependencies
- S017 - Base Infrastructure Setup
