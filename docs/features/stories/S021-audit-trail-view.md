# S021 - Audit Trail View

## Parent Feature
F006 - E2E Testing & Demo Application

## User Story

**As a** tester/operator
**I want** a UI to view the audit trail for a command
**So that** I can understand the full lifecycle and diagnose issues

## Context

Every command generates audit events throughout its lifecycle (SENT, RECEIVED, COMPLETED, FAILED, etc.). This view provides chronological visibility into these events.

## Acceptance Criteria

### Scenario: Search by command ID
**Given** I am on the Audit Trail page
**When** I enter a command_id
**And** I click "Search"
**Then** I see all audit events for that command in chronological order

### Scenario: Navigate from command details
**Given** I am viewing a command in the Commands browser
**When** I click "View Audit Trail"
**Then** I am taken to the Audit Trail page with that command's events displayed

### Scenario: View event details
**Given** audit events are displayed
**When** I click on an event
**Then** I see the full event details including JSON payload

### Scenario: Empty result
**Given** I am on the Audit Trail page
**When** I search for a non-existent command_id
**Then** I see a message "No audit events found for this command"

### Scenario: Event timeline visualization
**Given** audit events are displayed
**When** I view the events
**Then** events are shown in a timeline format
**And** time between events is visible
**And** each event type has a distinct icon/color

## UI Design

### Search Bar

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Audit Trail                                                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ Command ID: [________________________________] [Search]                      │
│                                                                              │
│ Or paste full UUID: abc12345-1234-1234-1234-123456789abc                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Timeline View

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Command: abc12345-1234-1234-1234-123456789abc                               │
│ Domain: test | Type: TestCommand | Status: COMPLETED                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ● SENT                                           2025-01-15 10:30:00.000   │
│  │  Command sent to queue                                                   │
│  │  msg_id: 42, correlation_id: xyz-123                                     │
│  │                                                               +0ms       │
│  │                                                                          │
│  ● RECEIVED                                       2025-01-15 10:30:00.150   │
│  │  Worker picked up command                                               │
│  │  worker_id: worker-1                                                    │
│  │                                                              +150ms      │
│  │                                                                          │
│  ● FAILED                                         2025-01-15 10:30:00.250   │
│  │  Transient failure, will retry                                          │
│  │  error_type: TRANSIENT, error_code: TIMEOUT                             │
│  │                                                              +100ms      │
│  │                                                                          │
│  ● RETRY_SCHEDULED                                2025-01-15 10:30:00.260   │
│  │  Scheduled for retry with backoff                                       │
│  │  next_attempt_at: 2025-01-15 10:30:05                                   │
│  │                                                               +10ms      │
│  │                                                                          │
│  ● RECEIVED                                       2025-01-15 10:30:05.100   │
│  │  Worker picked up command (attempt 2)                                   │
│  │                                                            +4840ms       │
│  │                                                                          │
│  ● COMPLETED                                      2025-01-15 10:30:05.200   │
│     Command completed successfully                                          │
│     result: {"status": "success"}                                          │
│                                                              +100ms         │
│                                                                              │
│  Total Duration: 5.2 seconds                                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Event Type Icons/Colors

| Event Type | Icon | Color |
|------------|------|-------|
| SENT | 📤 | Blue |
| RECEIVED | 📥 | Blue |
| COMPLETED | ✅ | Green |
| FAILED | ❌ | Red |
| RETRY_SCHEDULED | 🔄 | Yellow |
| RETRY_EXHAUSTED | ⚠️ | Orange |
| MOVED_TO_TSQ | 📋 | Orange |
| OPERATOR_RETRY | 🔁 | Purple |
| OPERATOR_CANCEL | 🚫 | Gray |
| OPERATOR_COMPLETE | ✔️ | Green |

### Event Detail Expansion

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ▼ FAILED                                          2025-01-15 10:30:00.250   │
├─────────────────────────────────────────────────────────────────────────────┤
│ Event ID: 12345                                                              │
│ Timestamp: 2025-01-15T10:30:00.250Z                                         │
│                                                                              │
│ Details:                                                                     │
│ ┌─────────────────────────────────────────────────────────────────────────┐ │
│ │ {                                                                        │ │
│ │   "error_type": "TRANSIENT",                                            │ │
│ │   "error_code": "TIMEOUT",                                              │ │
│ │   "error_message": "Database connection timeout",                       │ │
│ │   "attempt": 1,                                                         │ │
│ │   "max_attempts": 3                                                     │ │
│ │ }                                                                        │ │
│ └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

## API Endpoints

### GET /api/v1/audit/{command_id}
Get audit trail for a command.

**Response:**
```json
{
  "command_id": "uuid",
  "domain": "test",
  "command_type": "TestCommand",
  "current_status": "COMPLETED",
  "events": [
    {
      "audit_id": 1,
      "event_type": "SENT",
      "timestamp": "2025-01-15T10:30:00.000Z",
      "details": {
        "msg_id": 42,
        "correlation_id": "xyz-123"
      }
    },
    {
      "audit_id": 2,
      "event_type": "RECEIVED",
      "timestamp": "2025-01-15T10:30:00.150Z",
      "details": {
        "worker_id": "worker-1"
      }
    }
  ],
  "total_duration_ms": 5200
}
```

## Files to Create/Modify

- `tests/e2e/app/api/routes.py` - Add GET /audit/{command_id}
- `tests/e2e/app/templates/pages/audit.html`
- `tests/e2e/app/static/js/audit.js`

## Definition of Done

- [ ] Audit Trail page accessible from sidebar
- [ ] Search by command_id works
- [ ] Events displayed in chronological order
- [ ] Timeline visualization with time deltas
- [ ] Event type icons/colors implemented
- [ ] Event details expandable
- [ ] Navigation from other pages works
- [ ] Empty state for unknown commands
- [ ] Total duration calculated

## Story Size
M (2000-5000 tokens)

## Priority
Should Have

## Dependencies
- S017 - Base Infrastructure Setup
