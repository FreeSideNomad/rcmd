# S019 - Commands Browser View

## Parent Feature
F006 - E2E Testing & Demo Application

## User Story

**As a** tester/operator
**I want** a UI to browse and filter commands
**So that** I can monitor command status and find specific commands

## Context

This view provides a searchable, filterable, paginated list of all commands in the system. It leverages the `query_commands()` API from the commandbus library.

## Acceptance Criteria

### Scenario: View all commands
**Given** commands exist in the system
**When** I navigate to the Commands page
**Then** I see a paginated list of commands
**And** commands are sorted by created_at descending (newest first)

### Scenario: Filter by status
**Given** commands with various statuses exist
**When** I select status filter "PENDING"
**Then** only PENDING commands are displayed

### Scenario: Filter by domain
**Given** commands from multiple domains exist
**When** I enter domain filter "test"
**Then** only commands from the "test" domain are displayed

### Scenario: Filter by command type
**Given** commands with various types exist
**When** I enter command_type filter "TestCommand"
**Then** only TestCommand commands are displayed

### Scenario: Filter by date range
**Given** commands created at various times exist
**When** I set created_after to yesterday
**And** I set created_before to today
**Then** only commands from that date range are displayed

### Scenario: Combine multiple filters
**Given** various commands exist
**When** I set status to "PENDING"
**And** I set domain to "test"
**Then** only PENDING commands from "test" domain are displayed

### Scenario: Pagination
**Given** 200 commands exist
**When** I view the Commands page
**Then** I see the first 20 commands (configurable page size)
**And** pagination controls show page 1 of 10
**When** I click "Next"
**Then** I see commands 21-40

### Scenario: View command details
**Given** I am viewing the commands list
**When** I click on a command row
**Then** I see command details including metadata and audit trail link

## UI Design

### Filter Bar

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Filters                                                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│ Status: [All ▼]  Domain: [________]  Type: [________]                        │
│ From: [____/____/____]  To: [____/____/____]  [Apply Filters] [Clear]        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Commands Table

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Commands                                                    Page Size: [20▼] │
├─────────────────────────────────────────────────────────────────────────────┤
│ Command ID      │ Type        │ Status      │ Attempts │ Created            │
├─────────────────┼─────────────┼─────────────┼──────────┼────────────────────┤
│ abc-123...      │ TestCommand │ ● PENDING   │ 0/3      │ 2025-01-15 10:30   │
│ def-456...      │ TestCommand │ ● COMPLETED │ 1/3      │ 2025-01-15 10:28   │
│ ghi-789...      │ TestCommand │ ● FAILED    │ 3/3      │ 2025-01-15 10:25   │
└─────────────────┴─────────────┴─────────────┴──────────┴────────────────────┘
│ ◀ Previous   Page 1 of 10   Next ▶                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Status Badges

| Status | Color |
|--------|-------|
| PENDING | Yellow |
| IN_PROGRESS | Blue |
| COMPLETED | Green |
| FAILED | Red |
| IN_TSQ | Orange |
| CANCELLED | Gray |

### Command Detail Modal/Panel

```
┌─────────────────────────────────────────────────────────────┐
│ Command Details                                        [X]  │
├─────────────────────────────────────────────────────────────┤
│ Command ID: abc-123-def-456-ghi-789                         │
│ Domain: test                                                │
│ Type: TestCommand                                           │
│ Status: PENDING                                             │
│ Attempts: 0 / 3                                             │
│ Created: 2025-01-15 10:30:00 UTC                           │
│ Updated: 2025-01-15 10:30:00 UTC                           │
│                                                             │
│ Correlation ID: xyz-123-...                                 │
│                                                             │
│ Last Error: (none)                                          │
│                                                             │
│ [View Audit Trail]                                          │
└─────────────────────────────────────────────────────────────┘
```

## API Endpoints

### GET /api/v1/commands
Query commands with filters.

**Query Parameters:**
- `status` - Filter by status (PENDING, IN_PROGRESS, COMPLETED, etc.)
- `domain` - Filter by domain
- `command_type` - Filter by command type
- `created_after` - ISO datetime
- `created_before` - ISO datetime
- `limit` - Page size (default 20)
- `offset` - Pagination offset

**Response:**
```json
{
  "commands": [
    {
      "command_id": "uuid",
      "domain": "test",
      "command_type": "TestCommand",
      "status": "PENDING",
      "attempts": 0,
      "max_attempts": 3,
      "created_at": "2025-01-15T10:30:00Z",
      "updated_at": "2025-01-15T10:30:00Z",
      "correlation_id": "uuid",
      "last_error_code": null,
      "last_error_message": null
    }
  ],
  "total": 200,
  "limit": 20,
  "offset": 0
}
```

### GET /api/v1/commands/{command_id}
Get single command details.

## Files to Create/Modify

- `tests/e2e/app/api/routes.py` - Add GET /commands endpoint
- `tests/e2e/app/templates/pages/commands.html`
- `tests/e2e/app/static/js/commands.js`

## Definition of Done

- [ ] Commands page accessible from sidebar
- [ ] All filters work correctly
- [ ] Filters can be combined
- [ ] Pagination works correctly
- [ ] Status badges with correct colors
- [ ] Command detail view shows all metadata
- [ ] Link to audit trail works
- [ ] Page size configurable (10, 20, 50, 100)

## Story Size
M (2000-5000 tokens)

## Priority
Must Have

## Dependencies
- S017 - Base Infrastructure Setup
