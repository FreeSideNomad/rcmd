# S055: Expected Outcome Calculator in UI

## Parent Feature

[F011 - Probabilistic Test Command Behaviors](../F011-probabilistic-test-behaviors.md)

## User Story

**As a** user of the E2E demo application
**I want** to see expected outcome statistics based on my probability settings
**So that** I can understand what results to expect before creating commands

## Context

Add a real-time calculator that shows expected outcomes based on the configured probabilities. This helps users understand the sequential probability model and plan their test scenarios.

## Acceptance Criteria (Given-When-Then)

### Scenario: Display expected outcomes for single command

**Given** I am on the Send Command page
**When** I set fail_permanent_pct: 5, fail_transient_pct: 10, timeout_pct: 2
**Then** I see "Expected Outcomes (per 1000 commands):"
**And** the display shows:
  - ~50 permanent failures
  - ~95 transient failures
  - ~17 timeouts
  - ~838 successes

### Scenario: Update calculator in real-time

**Given** I am on the Send Command page
**And** fail_permanent_pct is set to 5%
**When** I change fail_permanent_pct to 10%
**Then** the expected outcomes update immediately
**And** permanent failures show ~100

### Scenario: Show correct sequential probability math

**Given** I set fail_permanent_pct: 50 and fail_transient_pct: 50
**When** I view the expected outcomes
**Then** permanent failures show ~500 (50%)
**And** transient failures show ~250 (50% of remaining 50%)
**And** successes show ~250 (remaining)

### Scenario: Bulk command outcome display

**Given** I am in the Bulk Create section
**And** count is set to 10000
**When** I set fail_permanent_pct: 5
**Then** I see "Expected Distribution:"
**And** the display shows ~500 permanent failures
**And** ~9500 successes

### Scenario: Visual bar chart for bulk

**Given** I am in the Bulk Create section
**And** I have configured probabilities
**When** the calculator updates
**Then** I see a horizontal bar chart showing relative proportions
**And** success bar is the largest (green)
**And** failure bars are proportionally smaller (red/orange)

## Test Mapping

| Criterion | Test Type | Test Location |
|-----------|-----------|---------------|
| Calculator displays | E2E | `tests/e2e/tests/test_ui.py::test_outcome_calculator` |
| Real-time updates | E2E | `tests/e2e/tests/test_ui.py::test_calculator_updates` |

## Story Size

S (1000-2000 tokens)

## Priority (MoSCoW)

Should Have

## Dependencies

- S053 (single command UI)
- S054 (bulk command UI)

## Technical Notes

### Calculation Logic

```javascript
function calculateExpectedOutcomes(count, failPermanent, failTransient, timeout) {
  // Sequential probability evaluation
  const permanentCount = count * (failPermanent / 100);
  const remainingAfterPermanent = count - permanentCount;

  const transientCount = remainingAfterPermanent * (failTransient / 100);
  const remainingAfterTransient = remainingAfterPermanent - transientCount;

  const timeoutCount = remainingAfterTransient * (timeout / 100);
  const successCount = remainingAfterTransient - timeoutCount;

  return {
    permanent: Math.round(permanentCount),
    transient: Math.round(transientCount),
    timeout: Math.round(timeoutCount),
    success: Math.round(successCount),
  };
}
```

### Template Addition

```html
<!-- Expected Outcomes Section -->
<div class="mt-4 p-4 bg-gray-50 rounded-lg"
     x-data="{
       get outcomes() {
         return calculateExpectedOutcomes(
           1000,
           this.behavior.fail_permanent_pct,
           this.behavior.fail_transient_pct,
           this.behavior.timeout_pct
         );
       }
     }">
  <h4 class="font-semibold text-sm text-gray-700">Expected Outcomes (per 1000 commands):</h4>
  <ul class="mt-2 text-sm space-y-1">
    <li class="text-red-600">
      ~<span x-text="outcomes.permanent"></span> permanent failures
    </li>
    <li class="text-orange-600">
      ~<span x-text="outcomes.transient"></span> transient failures
    </li>
    <li class="text-yellow-600">
      ~<span x-text="outcomes.timeout"></span> timeouts
    </li>
    <li class="text-green-600">
      ~<span x-text="outcomes.success"></span> successes
    </li>
  </ul>
</div>
```

### Bulk Visual Bar Chart

```html
<!-- Visual Distribution Bar -->
<div class="mt-4 h-6 flex rounded overflow-hidden">
  <div class="bg-green-500" :style="{ width: (outcomes.success / bulkCount * 100) + '%' }"></div>
  <div class="bg-red-500" :style="{ width: (outcomes.permanent / bulkCount * 100) + '%' }"></div>
  <div class="bg-orange-500" :style="{ width: (outcomes.transient / bulkCount * 100) + '%' }"></div>
  <div class="bg-yellow-500" :style="{ width: (outcomes.timeout / bulkCount * 100) + '%' }"></div>
</div>
```

## Files to Modify

- `tests/e2e/app/templates/pages/send_command.html` - Add outcome calculator
- `tests/e2e/app/static/js/send_command.js` - Add calculation function

## Definition of Done

- [ ] Expected outcomes section displays for single command
- [ ] Expected distribution displays for bulk
- [ ] Calculations update in real-time as probabilities change
- [ ] Sequential probability model correctly applied
- [ ] Visual bar chart shows proportions for bulk
- [ ] Color coding distinguishes outcome types
