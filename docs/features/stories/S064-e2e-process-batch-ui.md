# S064: E2E UI for Process Batch Initiation

## User Story

As a tester, I want a UI to initiate batches of StatementReportProcesses so that I can test process execution at scale.

## Acceptance Criteria

### AC1: Batch Form Page
- Given I navigate to `/processes/new-batch`
- When the page loads
- Then I see a form with fields: count, from_date, to_date, output_type

### AC2: Count Field
- Given the form is displayed
- When I enter a count (e.g., 10)
- Then that many processes will be created

### AC3: Date Range Fields
- Given the form is displayed
- When I enter from_date and to_date
- Then all processes will use these dates

### AC4: Output Type Selection
- Given the form is displayed
- When I select output_type (PDF, HTML, CSV)
- Then all processes will use this output format

### AC5: Random Account Generation
- Given the form is submitted
- When processes are created
- Then each process gets a random list of 3 account IDs

### AC6: Batch Creation
- Given all form fields are valid
- When I click "Create Batch"
- Then:
  1. API creates n StatementReportProcesses
  2. Each process starts with generated fake data
  3. User is redirected to process list page

### AC7: Validation
- Given form has invalid data
- When I submit
- Then validation errors are displayed

## Implementation Notes

- Location: `tests/e2e/app/templates/pages/process_batch_form.html`
- Web route: `tests/e2e/app/web/routes.py`
- API endpoint: `POST /api/processes/batch`

## API Request/Response

```python
# Request
class ProcessBatchRequest(BaseModel):
    count: int = Field(ge=1, le=100)
    from_date: date
    to_date: date
    output_type: str  # "pdf", "html", "csv"

# Response
class ProcessBatchResponse(BaseModel):
    process_ids: list[UUID]
    batch_id: UUID | None  # If using F009 batch tracking
```

## Form Template

```html
<form method="POST" action="/api/processes/batch">
    <div class="form-group">
        <label>Number of Processes</label>
        <input type="number" name="count" min="1" max="100" value="10">
    </div>

    <div class="form-group">
        <label>From Date</label>
        <input type="date" name="from_date" required>
    </div>

    <div class="form-group">
        <label>To Date</label>
        <input type="date" name="to_date" required>
    </div>

    <div class="form-group">
        <label>Output Type</label>
        <select name="output_type">
            <option value="pdf">PDF</option>
            <option value="html">HTML</option>
            <option value="csv">CSV</option>
        </select>
    </div>

    <button type="submit">Create Batch</button>
</form>
```

## Fake Data Generation

```python
import random
import string

def generate_fake_accounts(count: int = 3) -> list[str]:
    """Generate random account IDs."""
    return [
        f"ACC-{''.join(random.choices(string.digits, k=6))}"
        for _ in range(count)
    ]
```

## Verification

- [ ] Form renders with all fields
- [ ] Count validation (1-100)
- [ ] Date validation (from <= to)
- [ ] Output type dropdown works
- [ ] Batch creation creates correct number of processes
- [ ] Redirect to process list after creation
