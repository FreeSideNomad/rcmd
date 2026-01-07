# S066: E2E UI for Process Details and Audit

## User Story

As a tester, I want a detailed view of each process showing its state and audit trail so that I can understand execution flow and debug issues.

## Acceptance Criteria

### AC1: Process Detail Page
- Given I navigate to `/processes/{process_id}`
- When the page loads
- Then I see process metadata, state, and audit trail

### AC2: Process Metadata Display
- Given the detail page loads
- When I view the metadata section
- Then I see: process_id, process_type, domain, status, current_step, created_at, updated_at, completed_at

### AC3: Error Information
- Given a process has failed
- When I view the detail page
- Then I see error_code and error_message prominently displayed

### AC4: State JSON Display
- Given the process has state
- When I view the state section
- Then I see formatted JSON of the process state

### AC5: Audit Trail Table
- Given the process has executed steps
- When I view the audit section
- Then I see a table with: step_name, command_type, command_id, sent_at, outcome, received_at, duration

### AC6: Command Data Expansion
- Given an audit entry has command_data
- When I click to expand
- Then I see the full command payload as JSON

### AC7: Reply Data Expansion
- Given an audit entry has reply_data
- When I click to expand
- Then I see the full reply payload as JSON

### AC8: Step Status Indicators
- Given audit entries have different outcomes
- When displayed
- Then SUCCESS shows green, FAILED shows red, pending shows gray

### AC9: Back to List
- Given I'm viewing details
- When I click "Back to List"
- Then I return to the process list page

## Implementation Notes

- Location: `tests/e2e/app/templates/pages/process_detail.html`
- Web route: `GET /processes/{process_id}` in `tests/e2e/app/web/routes.py`
- API endpoint: `GET /api/processes/{process_id}`

## API Response

```python
class ProcessDetailResponse(BaseModel):
    process_id: UUID
    domain: str
    process_type: str
    status: str
    current_step: str | None
    state: dict[str, Any]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    audit_trail: list[AuditEntryResponse]

class AuditEntryResponse(BaseModel):
    step_name: str
    command_id: UUID
    command_type: str
    command_data: dict[str, Any] | None
    sent_at: datetime
    reply_outcome: str | None
    reply_data: dict[str, Any] | None
    received_at: datetime | None
```

## Template Structure

```html
{% extends "base.html" %}

{% block content %}
<div class="container">
    <a href="/processes" class="back-link">&larr; Back to List</a>

    <h1>Process {{ process.process_id | truncate(8) }}</h1>

    <!-- Metadata Section -->
    <div class="card">
        <h2>Metadata</h2>
        <dl>
            <dt>Process ID</dt><dd>{{ process.process_id }}</dd>
            <dt>Type</dt><dd>{{ process.process_type }}</dd>
            <dt>Domain</dt><dd>{{ process.domain }}</dd>
            <dt>Status</dt><dd><span class="badge">{{ process.status }}</span></dd>
            <dt>Current Step</dt><dd>{{ process.current_step or "-" }}</dd>
            <dt>Created</dt><dd>{{ process.created_at }}</dd>
            <dt>Updated</dt><dd>{{ process.updated_at }}</dd>
            <dt>Completed</dt><dd>{{ process.completed_at or "-" }}</dd>
        </dl>
    </div>

    <!-- Error Section (if failed) -->
    {% if process.error_code %}
    <div class="card error">
        <h2>Error</h2>
        <p><strong>Code:</strong> {{ process.error_code }}</p>
        <p><strong>Message:</strong> {{ process.error_message }}</p>
    </div>
    {% endif %}

    <!-- State Section -->
    <div class="card">
        <h2>State</h2>
        <pre><code>{{ process.state | tojson(indent=2) }}</code></pre>
    </div>

    <!-- Audit Trail Section -->
    <div class="card">
        <h2>Audit Trail</h2>
        <table class="table">
            <thead>
                <tr>
                    <th>Step</th>
                    <th>Command</th>
                    <th>Sent</th>
                    <th>Outcome</th>
                    <th>Received</th>
                    <th>Duration</th>
                </tr>
            </thead>
            <tbody>
                {% for entry in process.audit_trail %}
                <tr>
                    <td>{{ entry.step_name }}</td>
                    <td>
                        {{ entry.command_type }}
                        <button onclick="toggleData('cmd-{{ entry.command_id }}')">Show Data</button>
                        <div id="cmd-{{ entry.command_id }}" class="hidden">
                            <pre>{{ entry.command_data | tojson(indent=2) }}</pre>
                        </div>
                    </td>
                    <td>{{ entry.sent_at | timeago }}</td>
                    <td>
                        {% if entry.reply_outcome %}
                        <span class="badge badge-{{ entry.reply_outcome | lower }}">
                            {{ entry.reply_outcome }}
                        </span>
                        {% else %}
                        <span class="badge badge-pending">Pending</span>
                        {% endif %}
                    </td>
                    <td>{{ entry.received_at | timeago if entry.received_at else "-" }}</td>
                    <td>{{ calculate_duration(entry) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<script>
function toggleData(id) {
    document.getElementById(id).classList.toggle('hidden');
}
</script>
{% endblock %}
```

## Duration Calculation

```python
def calculate_duration(entry: AuditEntryResponse) -> str:
    if not entry.received_at:
        return "-"
    delta = entry.received_at - entry.sent_at
    seconds = delta.total_seconds()
    if seconds < 1:
        return f"{int(seconds * 1000)}ms"
    return f"{seconds:.1f}s"
```

## Verification

- [ ] Page loads with process data
- [ ] Metadata displays all fields correctly
- [ ] Error section shows for failed processes
- [ ] State JSON is formatted and readable
- [ ] Audit trail shows all steps
- [ ] Command/reply data can be expanded
- [ ] Duration calculated correctly
- [ ] Back link works
