# S022 - Dashboard View

## Parent Feature
F006 - E2E Testing & Demo Application

## User Story

**As a** tester/operator
**I want** a dashboard showing system overview and statistics
**So that** I can quickly assess system health and activity

## Context

The dashboard provides at-a-glance visibility into the command bus system, including counts by status, recent activity, and quick actions.

## Acceptance Criteria

### Scenario: View status counts
**Given** commands exist in various states
**When** I navigate to the Dashboard
**Then** I see count cards for each status (PENDING, IN_PROGRESS, COMPLETED, FAILED, IN_TSQ, CANCELLED)

### Scenario: Counts refresh automatically
**Given** I am on the Dashboard
**When** commands are processed in the background
**Then** counts update automatically (polling every 5 seconds)

### Scenario: Click status to filter
**Given** I see status count cards
**When** I click on "PENDING (15)"
**Then** I am navigated to Commands page filtered by status=PENDING

### Scenario: View recent commands
**Given** commands exist
**When** I view the Dashboard
**Then** I see the 5 most recently created commands
**And** I see the 5 most recently completed commands

### Scenario: Quick send command
**Given** I am on the Dashboard
**When** I use the quick send form
**Then** I can send a test command with default success behavior
**And** the counts update immediately

### Scenario: View processing metrics (if workers running)
**Given** workers are processing commands
**When** I view the Dashboard
**Then** I see processing rate (commands/minute)
**And** I see average processing time

## UI Design

### Status Cards Row

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Dashboard                                                     Last updated: now│
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ PENDING  │  │IN_PROGRESS│ │ COMPLETED│  │  FAILED  │  │  IN_TSQ  │        │
│  │    15    │  │     3    │  │   1,234  │  │    12    │  │    5     │        │
│  │    ⏳    │  │    🔄    │  │    ✅    │  │    ❌    │  │    ⚠️    │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Recent Activity Section

```
┌─────────────────────────────────────┬─────────────────────────────────────────┐
│ Recently Created                    │ Recently Completed                       │
├─────────────────────────────────────┼─────────────────────────────────────────┤
│ abc-123... TestCommand  10:30:00    │ xyz-789... TestCommand  10:29:55 ✅     │
│ def-456... TestCommand  10:29:58    │ uvw-456... TestCommand  10:29:50 ✅     │
│ ghi-789... TestCommand  10:29:55    │ rst-123... TestCommand  10:29:45 ✅     │
│ jkl-012... TestCommand  10:29:52    │ opq-890... TestCommand  10:29:40 ✅     │
│ mno-345... TestCommand  10:29:50    │ lmn-567... TestCommand  10:29:35 ✅     │
├─────────────────────────────────────┴─────────────────────────────────────────┤
│                            [View All Commands]                                 │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Processing Metrics (optional - shown if workers active)

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Processing Metrics (last 5 minutes)                                           │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Processing Rate: 45 commands/min          Avg Processing Time: 125ms         │
│                                                                                │
│  ████████████████████░░░░░░░░░░░░░░░░░░░░  Queue Depth: 15                    │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Quick Actions

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Quick Actions                                                                  │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  [📤 Send Test Command]  [🔄 Generate 100 Commands]  [⚙️ Start Worker]        │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

## API Endpoints

### GET /api/v1/stats
Get dashboard statistics.

**Response:**
```json
{
  "counts": {
    "PENDING": 15,
    "IN_PROGRESS": 3,
    "COMPLETED": 1234,
    "FAILED": 0,
    "IN_TSQ": 5,
    "CANCELLED": 2
  },
  "recent_created": [
    {
      "command_id": "abc-123",
      "command_type": "TestCommand",
      "created_at": "2025-01-15T10:30:00Z"
    }
  ],
  "recent_completed": [
    {
      "command_id": "xyz-789",
      "command_type": "TestCommand",
      "completed_at": "2025-01-15T10:29:55Z"
    }
  ],
  "metrics": {
    "processing_rate_per_minute": 45,
    "avg_processing_time_ms": 125,
    "queue_depth": 15
  },
  "last_updated": "2025-01-15T10:30:05Z"
}
```

### POST /api/v1/commands/quick
Send a quick test command (success behavior).

**Response:**
```json
{
  "command_id": "uuid",
  "status": "PENDING"
}
```

## Files to Create/Modify

- `tests/e2e/app/api/routes.py` - Add GET /stats endpoint
- `tests/e2e/app/templates/pages/dashboard.html`
- `tests/e2e/app/static/js/dashboard.js`

## Definition of Done

- [ ] Dashboard is the default landing page
- [ ] Status count cards display correctly
- [ ] Counts auto-refresh every 5 seconds
- [ ] Clicking status card navigates to filtered Commands view
- [ ] Recent created/completed commands displayed
- [ ] Quick send command works
- [ ] Processing metrics shown (optional)
- [ ] Responsive layout

## Story Size
M (2000-5000 tokens)

## Priority
Should Have

## Dependencies
- S017 - Base Infrastructure Setup
- S018 - Send Command View (for quick send)
- S019 - Commands Browser View (for navigation)
