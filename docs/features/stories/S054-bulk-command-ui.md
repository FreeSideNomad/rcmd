# S054: Bulk Command UI with Probability Inputs

## Parent Feature

[F011 - Probabilistic Test Command Behaviors](../F011-probabilistic-test-behaviors.md)

## User Story

**As a** user of the E2E demo application
**I want** to configure failure probabilities when creating bulk commands
**So that** I can generate large test batches with realistic failure distributions

## Context

Update the Bulk Create section of the Send Command page to use probabilistic behavior configuration. Users should be able to set probabilities for the entire batch, with each command's actual behavior determined at execution time.

## Acceptance Criteria (Given-When-Then)

### Scenario: Display probability inputs for bulk

**Given** I navigate to the Bulk Create section
**When** the section loads
**Then** I see probability input fields for:
  - Permanent Failure (%)
  - Transient Failure (%)
  - Timeout (%)
  - Min Duration (ms)
  - Max Duration (ms)

### Scenario: Create bulk with probabilities

**Given** I am in the Bulk Create section
**When** I set count to 1000 and fail_permanent_pct to 5
**And** I click "Create Commands"
**Then** 1000 commands are created
**And** each command has the same behavior configuration
**And** ~50 commands will fail permanently when processed

### Scenario: Remove behavior distribution

**Given** I navigate to the Bulk Create section
**When** the section loads
**Then** there is no "Behavior Distribution" option
**And** only probabilistic configuration is available

### Scenario: Validation for bulk probabilities

**Given** I am in the Bulk Create section
**When** I enter fail_permanent_pct: -5
**Then** validation shows an error
**And** the form cannot be submitted

### Scenario: Default bulk probabilities

**Given** I navigate to the Bulk Create section
**When** I don't change any probability values
**Then** all probabilities default to 0
**And** duration values default to 0
**And** all commands will succeed immediately when processed

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Probability inputs render | E2E | `tests/e2e/tests/test_ui.py::test_bulk_probability_inputs` |
| Create bulk with probabilities | E2E | `tests/e2e/tests/test_ui.py::test_bulk_create_probabilistic` |

## Story Size

S (1000-2000 tokens)

## Priority (MoSCoW)

Must Have

## Dependencies

- S052 (API schemas must accept probabilistic behavior)
- S053 (design pattern established for probability inputs)

## Technical Notes

### Template Changes

Update `tests/e2e/app/templates/pages/send_command.html` bulk section:

```html
<!-- Bulk Create Section -->
<div class="border-t pt-6 mt-6">
  <h2 class="text-xl font-bold mb-4">Bulk Create Commands</h2>

  <div class="space-y-4">
    <div>
      <label>Count</label>
      <input type="number" min="1" max="1000000" x-model="bulkCount">
    </div>

    <div class="grid grid-cols-3 gap-4">
      <div>
        <label>Permanent Failure %</label>
        <input type="number" min="0" max="100" step="0.1"
               x-model="bulkBehavior.fail_permanent_pct">
      </div>
      <div>
        <label>Transient Failure %</label>
        <input type="number" min="0" max="100" step="0.1"
               x-model="bulkBehavior.fail_transient_pct">
      </div>
      <div>
        <label>Timeout %</label>
        <input type="number" min="0" max="100" step="0.1"
               x-model="bulkBehavior.timeout_pct">
      </div>
    </div>

    <div class="grid grid-cols-2 gap-4">
      <div>
        <label>Min Duration (ms)</label>
        <input type="number" min="0" x-model="bulkBehavior.min_duration_ms">
      </div>
      <div>
        <label>Max Duration (ms)</label>
        <input type="number" min="0" x-model="bulkBehavior.max_duration_ms">
      </div>
    </div>

    <button @click="createBulk()" class="btn btn-primary">
      Create <span x-text="bulkCount"></span> Commands
    </button>
  </div>
</div>
```

### JavaScript Changes

Update `tests/e2e/app/static/js/send_command.js`:

```javascript
bulkBehavior: {
  fail_permanent_pct: 0,
  fail_transient_pct: 0,
  timeout_pct: 0,
  min_duration_ms: 0,
  max_duration_ms: 0,
},

async createBulk() {
  const response = await fetch('/api/commands/bulk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      count: parseInt(this.bulkCount),
      behavior: {
        fail_permanent_pct: parseFloat(this.bulkBehavior.fail_permanent_pct) || 0,
        fail_transient_pct: parseFloat(this.bulkBehavior.fail_transient_pct) || 0,
        timeout_pct: parseFloat(this.bulkBehavior.timeout_pct) || 0,
        min_duration_ms: parseInt(this.bulkBehavior.min_duration_ms) || 0,
        max_duration_ms: parseInt(this.bulkBehavior.max_duration_ms) || 0,
      },
    }),
  });
  // Handle response...
}
```

## Files to Modify

- `tests/e2e/app/templates/pages/send_command.html` - Update bulk create section
- `tests/e2e/app/static/js/send_command.js` - Update bulk form handling

## Definition of Done

- [ ] Behavior distribution option removed
- [ ] Probability inputs displayed for bulk
- [ ] Duration inputs displayed for bulk
- [ ] Form validates probability range (0-100)
- [ ] Bulk create submits probabilistic behavior
- [ ] All bulk commands receive same behavior config
