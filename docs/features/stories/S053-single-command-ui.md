# S053: Single Command UI with Probability Sliders

## Parent Feature

[F011 - Probabilistic Test Command Behaviors](../F011-probabilistic-test-behaviors.md)

## User Story

**As a** user of the E2E demo application
**I want** to configure failure probabilities using sliders in the Send Command form
**So that** I can easily create test commands with specific failure rates

## Context

Update the Send Command page to replace the behavior type dropdown with probability sliders. Users should be able to visually set failure percentages and duration ranges.

## Acceptance Criteria (Given-When-Then)

### Scenario: Display probability sliders

**Given** I navigate to the Send Command page
**When** the page loads
**Then** I see three probability sliders:
  - Permanent Failure (0-100%)
  - Transient Failure (0-100%)
  - Timeout (0-100%)
**And** all sliders default to 0%

### Scenario: Adjust probability with slider

**Given** I am on the Send Command page
**When** I drag the Permanent Failure slider to 25%
**Then** the slider shows 25%
**And** a numeric input displays 25.0

### Scenario: Enter probability numerically

**Given** I am on the Send Command page
**When** I type 33.5 in the Permanent Failure input
**Then** the slider updates to 33.5%
**And** the input shows 33.5

### Scenario: Configure duration range

**Given** I am on the Send Command page
**When** I set Min Duration to 50ms and Max Duration to 200ms
**Then** both values are displayed
**And** a helper text shows "Normal distribution (mean=125ms)"

### Scenario: Submit command with probabilities

**Given** I have configured fail_permanent_pct: 10 and min_duration_ms: 100
**When** I click "Send Command"
**Then** the command is created successfully
**And** the behavior JSON includes the probabilistic configuration

### Scenario: Remove old behavior type dropdown

**Given** I navigate to the Send Command page
**When** the page loads
**Then** there is no "Behavior Type" dropdown
**And** only probability sliders are displayed

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Sliders render | E2E | `tests/e2e/tests/test_ui.py::test_send_command_sliders` |
| Submit with probabilities | E2E | `tests/e2e/tests/test_ui.py::test_send_probabilistic_command` |

## Story Size

M (2000-4000 tokens)

## Priority (MoSCoW)

Must Have

## Dependencies

- S052 (API schemas must accept probabilistic behavior)

## Technical Notes

### Template Changes

Update `tests/e2e/app/templates/pages/send_command.html`:

```html
<!-- Probability Sliders -->
<div class="space-y-4">
  <h3 class="text-lg font-semibold">Failure Probabilities</h3>

  <div>
    <label>Permanent Failure</label>
    <input type="range" min="0" max="100" step="0.1"
           x-model="behavior.fail_permanent_pct">
    <input type="number" min="0" max="100" step="0.1"
           x-model="behavior.fail_permanent_pct">
    <span>%</span>
  </div>

  <div>
    <label>Transient Failure</label>
    <input type="range" min="0" max="100" step="0.1"
           x-model="behavior.fail_transient_pct">
    <input type="number" min="0" max="100" step="0.1"
           x-model="behavior.fail_transient_pct">
    <span>%</span>
  </div>

  <div>
    <label>Timeout</label>
    <input type="range" min="0" max="100" step="0.1"
           x-model="behavior.timeout_pct">
    <input type="number" min="0" max="100" step="0.1"
           x-model="behavior.timeout_pct">
    <span>%</span>
  </div>
</div>

<!-- Duration Range -->
<div class="space-y-2">
  <h3 class="text-lg font-semibold">Success Duration</h3>
  <div class="flex space-x-4">
    <div>
      <label>Min (ms)</label>
      <input type="number" min="0" x-model="behavior.min_duration_ms">
    </div>
    <div>
      <label>Max (ms)</label>
      <input type="number" min="0" x-model="behavior.max_duration_ms">
    </div>
  </div>
  <p class="text-sm text-gray-500" x-show="behavior.max_duration_ms > behavior.min_duration_ms">
    Normal distribution (mean=<span x-text="(behavior.min_duration_ms + behavior.max_duration_ms) / 2"></span>ms)
  </p>
</div>
```

### JavaScript Changes

Update the form submission in `tests/e2e/app/static/js/send_command.js`:

```javascript
const behavior = {
  fail_permanent_pct: parseFloat(this.behavior.fail_permanent_pct) || 0,
  fail_transient_pct: parseFloat(this.behavior.fail_transient_pct) || 0,
  timeout_pct: parseFloat(this.behavior.timeout_pct) || 0,
  min_duration_ms: parseInt(this.behavior.min_duration_ms) || 0,
  max_duration_ms: parseInt(this.behavior.max_duration_ms) || 0,
};
```

## Files to Modify

- `tests/e2e/app/templates/pages/send_command.html` - Replace dropdown with sliders
- `tests/e2e/app/static/js/send_command.js` - Update form data handling

## Definition of Done

- [ ] Behavior type dropdown removed
- [ ] Three probability sliders displayed
- [ ] Sliders sync with numeric inputs
- [ ] Duration range inputs displayed
- [ ] Mean calculation shown for duration
- [ ] Form submits probabilistic behavior correctly
- [ ] Command created successfully with new format
