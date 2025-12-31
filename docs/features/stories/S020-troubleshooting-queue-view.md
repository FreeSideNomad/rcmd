# S020 - Troubleshooting Queue View

## Parent Feature
F006 - E2E Testing & Demo Application

## User Story

**As an** operator
**I want** a UI to manage commands in the troubleshooting queue
**So that** I can retry, cancel, or manually complete failed commands

## Context

Commands that fail permanently or exhaust their retries end up in the Troubleshooting Queue (TSQ). This view provides operators with visibility into failed commands and actions to resolve them.

## Acceptance Criteria

### Scenario: View commands in TSQ
**Given** commands exist in the troubleshooting queue
**When** I navigate to the Troubleshooting page
**Then** I see a list of all commands with status IN_TSQ
**And** each command shows error details (code, message)

### Scenario: Retry a command
**Given** a command is in the TSQ
**When** I click "Retry" on that command
**Then** the command is re-queued for processing
**And** the command status changes to PENDING
**And** a success message is displayed
**And** the command disappears from the TSQ list

### Scenario: Cancel a command
**Given** a command is in the TSQ
**When** I click "Cancel" on that command
**And** I confirm the cancellation
**Then** the command status changes to CANCELLED
**And** a success message is displayed
**And** the command disappears from the TSQ list

### Scenario: Manually complete a command
**Given** a command is in the TSQ
**When** I click "Complete" on that command
**And** I optionally enter result data
**And** I confirm
**Then** the command status changes to COMPLETED
**And** the audit trail shows OPERATOR_COMPLETE event
**And** a success message is displayed

### Scenario: View command error details
**Given** a command is in the TSQ
**When** I expand the command row
**Then** I see full error details including:
  - Error type (TRANSIENT/PERMANENT)
  - Error code
  - Error message
  - Number of attempts
  - Original payload (from test_command)

### Scenario: Bulk retry
**Given** multiple commands are in the TSQ
**When** I select multiple commands
**And** I click "Retry Selected"
**Then** all selected commands are re-queued
**And** a summary shows "N commands retried"

### Scenario: Filter TSQ by domain
**Given** TSQ commands from multiple domains exist
**When** I filter by domain "test"
**Then** only commands from "test" domain are shown

## UI Design

### TSQ Table

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Troubleshooting Queue                               [Retry Selected] [□ All]│
├─────────────────────────────────────────────────────────────────────────────┤
│ Domain: [All ▼]                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ □ │ Command ID      │ Type        │ Error         │ Attempts │ Actions      │
├───┼─────────────────┼─────────────┼───────────────┼──────────┼──────────────┤
│ □ │ abc-123...      │ TestCommand │ INVALID_DATA  │ 3/3      │ [▶][✓][✗][▼]│
│ □ │ def-456...      │ TestCommand │ PERMANENT_ERR │ 1/3      │ [▶][✓][✗][▼]│
└───┴─────────────────┴─────────────┴───────────────┴──────────┴──────────────┘
```

### Action Buttons

| Icon | Action | Description |
|------|--------|-------------|
| ▶ | Retry | Re-queue command for processing |
| ✓ | Complete | Mark as manually completed |
| ✗ | Cancel | Cancel the command |
| ▼ | Expand | Show error details |

### Expanded Error Details

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ▲ abc-123-def-456-ghi-789                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ Error Type: PERMANENT                                                        │
│ Error Code: INVALID_DATA                                                     │
│ Error Message: Account not found in system                                  │
│                                                                              │
│ Attempts: 3 of 3                                                             │
│ First Failure: 2025-01-15 10:30:00 UTC                                      │
│ Last Failure: 2025-01-15 10:35:00 UTC                                       │
│                                                                              │
│ Original Behavior: {"type": "fail_permanent", "error_code": "INVALID_DATA"} │
│                                                                              │
│ [View Audit Trail]                                                           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Complete Modal

```
┌─────────────────────────────────────────────────────────────┐
│ Complete Command Manually                              [X]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│ Command: abc-123-def-456-ghi-789                           │
│                                                             │
│ Result Data (optional):                                     │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ { "manually_resolved": true, "notes": "..." }           │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ Operator Notes:                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Resolved by contacting customer directly                │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│                     [Cancel] [Complete]                     │
└─────────────────────────────────────────────────────────────┘
```

## API Endpoints

### GET /api/v1/tsq
List commands in troubleshooting queue.

**Query Parameters:**
- `domain` - Filter by domain
- `limit` - Page size
- `offset` - Pagination offset

**Response:**
```json
{
  "commands": [
    {
      "command_id": "uuid",
      "domain": "test",
      "command_type": "TestCommand",
      "attempts": 3,
      "max_attempts": 3,
      "last_error_type": "PERMANENT",
      "last_error_code": "INVALID_DATA",
      "last_error_message": "Account not found",
      "created_at": "2025-01-15T10:30:00Z",
      "updated_at": "2025-01-15T10:35:00Z"
    }
  ],
  "total": 5
}
```

### POST /api/v1/tsq/{command_id}/retry
Retry a command from TSQ.

### POST /api/v1/tsq/{command_id}/cancel
Cancel a command in TSQ.

### POST /api/v1/tsq/{command_id}/complete
Manually complete a command.

**Request:**
```json
{
  "result_data": {"manually_resolved": true},
  "operator": "admin"
}
```

### POST /api/v1/tsq/bulk-retry
Retry multiple commands.

**Request:**
```json
{
  "command_ids": ["uuid1", "uuid2", "uuid3"]
}
```

## Files to Create/Modify

- `tests/e2e/app/api/routes.py` - Add TSQ endpoints
- `tests/e2e/app/templates/pages/troubleshooting.html`
- `tests/e2e/app/static/js/troubleshooting.js`

## Definition of Done

- [ ] TSQ page accessible from sidebar
- [ ] List shows all IN_TSQ commands
- [ ] Retry action works correctly
- [ ] Cancel action works with confirmation
- [ ] Complete action works with optional result data
- [ ] Bulk retry works for selected commands
- [ ] Domain filter works
- [ ] Error details expandable
- [ ] Audit trail link works
- [ ] Success/error feedback for all actions

## Story Size
M (2000-5000 tokens)

## Priority
Must Have

## Dependencies
- S017 - Base Infrastructure Setup
