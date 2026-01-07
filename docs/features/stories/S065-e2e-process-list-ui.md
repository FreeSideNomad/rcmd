# S065: E2E UI for Process List

## User Story

As a tester, I want a UI to view all processes so that I can monitor execution and find specific processes.

## Acceptance Criteria

### AC1: Process List Page
- Given I navigate to `/processes`
- When the page loads
- Then I see a table of all processes

### AC2: Table Columns
- Given the process list is displayed
- When I view the table
- Then I see columns: process_id, process_type, status, current_step, created_at

### AC3: Status Filter
- Given the process list is displayed
- When I select a status filter (e.g., COMPLETED)
- Then only processes with that status are shown

### AC4: Status Badges
- Given processes have different statuses
- When displayed in the table
- Then status shows as colored badge (green=COMPLETED, yellow=IN_PROGRESS, red=FAILED)

### AC5: Detail Link
- Given a process is listed
- When I click on the process_id
- Then I navigate to `/processes/{process_id}` detail page

### AC6: Pagination
- Given there are many processes
- When the list loads
- Then results are paginated (e.g., 25 per page)

### AC7: Auto-Refresh
- Given processes are in progress
- When viewing the list
- Then it auto-refreshes every 5 seconds (optional enhancement)

### AC8: Create Batch Button
- Given I'm on the process list
- When I click "Create Batch"
- Then I navigate to the batch creation form

## Implementation Notes

- Location: `tests/e2e/app/templates/pages/processes.html`
- Web route: `GET /processes` in `tests/e2e/app/web/routes.py`
- API endpoint: `GET /api/processes?status=...&limit=...&offset=...`

## API Response

```python
class ProcessListItem(BaseModel):
    process_id: UUID
    process_type: str
    status: str
    current_step: str | None
    created_at: datetime
    updated_at: datetime

class ProcessListResponse(BaseModel):
    processes: list[ProcessListItem]
    total: int
    limit: int
    offset: int
```

## Template Structure

```html
{% extends "base.html" %}

{% block content %}
<div class="container">
    <h1>Processes</h1>

    <div class="toolbar">
        <a href="/processes/new-batch" class="btn btn-primary">Create Batch</a>

        <select id="status-filter" onchange="filterByStatus()">
            <option value="">All Statuses</option>
            <option value="PENDING">Pending</option>
            <option value="IN_PROGRESS">In Progress</option>
            <option value="WAITING">Waiting</option>
            <option value="COMPLETED">Completed</option>
            <option value="FAILED">Failed</option>
        </select>
    </div>

    <table class="table">
        <thead>
            <tr>
                <th>Process ID</th>
                <th>Type</th>
                <th>Status</th>
                <th>Current Step</th>
                <th>Created</th>
            </tr>
        </thead>
        <tbody>
            {% for process in processes %}
            <tr>
                <td><a href="/processes/{{ process.process_id }}">{{ process.process_id | truncate(8) }}</a></td>
                <td>{{ process.process_type }}</td>
                <td><span class="badge badge-{{ process.status | lower }}">{{ process.status }}</span></td>
                <td>{{ process.current_step or "-" }}</td>
                <td>{{ process.created_at | timeago }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>

    {% include "partials/pagination.html" %}
</div>
{% endblock %}
```

## Status Badge Colors

```css
.badge-pending { background: #6c757d; }      /* gray */
.badge-in_progress { background: #007bff; }  /* blue */
.badge-waiting { background: #ffc107; }      /* yellow */
.badge-completed { background: #28a745; }    /* green */
.badge-failed { background: #dc3545; }       /* red */
.badge-compensated { background: #17a2b8; }  /* cyan */
```

## Verification

- [ ] List displays all processes
- [ ] Status filter works correctly
- [ ] Process IDs link to detail page
- [ ] Pagination works for large lists
- [ ] Status badges have correct colors
- [ ] Create Batch button navigates correctly
