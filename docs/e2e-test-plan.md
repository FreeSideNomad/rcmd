# E2E Test Plan - Command Bus Demo Application

## Document Information

| Field | Value |
|-------|-------|
| Version | 1.0 |
| Created | 2026-01-02 |
| Author | Development Team |
| Status | Draft |
| Application | Command Bus E2E Demo Application |

---

## 1. Test Strategy

### 1.1 Scope

This test plan covers manual End-to-End (E2E) UI testing for the Command Bus Demo Application. The application provides a web interface for:
- Sending test commands with configurable behaviors
- Browsing and filtering commands
- Managing commands in the Troubleshooting Queue (TSQ)
- Viewing audit trails
- Monitoring processing statistics

### 1.2 Test Objectives

1. Verify all UI components render correctly
2. Validate form submissions and API interactions
3. Ensure proper error handling and user feedback
4. Confirm navigation and page transitions work correctly
5. Test end-to-end command lifecycle workflows

### 1.3 Test Environment

| Component | Requirement |
|-----------|-------------|
| Browser | Chrome (latest), Firefox (latest), Safari (latest) |
| Resolution | Desktop: 1920x1080, Tablet: 768x1024, Mobile: 375x667 |
| Database | PostgreSQL 15+ with PGMQ extension |
| Backend | Flask 3.x running on localhost:5000 |
| Workers | At least 1 worker process running |

### 1.4 Test Approach

- **Functional Testing**: Verify all features work as expected
- **UI Testing**: Verify layout, styling, and responsiveness
- **Integration Testing**: Verify UI interacts correctly with backend APIs
- **Workflow Testing**: Verify complete end-to-end scenarios

### 1.5 Entry/Exit Criteria

**Entry Criteria:**
- Application is deployed and accessible
- Database is running with schema initialized
- At least one worker process is running
- Test data has been set up

**Exit Criteria:**
- All P1 (Critical) test cases pass
- No more than 2 P2 (High) test cases fail
- All blocking defects are resolved

---

## 2. Test Data

### 2.1 Test Data Setup

Before executing tests, ensure the database is clean:

```sql
-- Clean test data
DELETE FROM command_bus_audit WHERE domain = 'e2e';
DELETE FROM command_bus_command WHERE domain = 'e2e';
DELETE FROM pgmq.q_e2e__commands;
DELETE FROM pgmq.a_e2e__commands;
```

### 2.2 Sample Test Data

#### TD-001: Success Command
```json
{
  "behavior": {
    "type": "success",
    "execution_time_ms": 100
  },
  "payload": {
    "test_id": "TD-001",
    "description": "Success command for testing"
  }
}
```

#### TD-002: Permanent Failure Command
```json
{
  "behavior": {
    "type": "fail_permanent",
    "error_code": "INVALID_ACCOUNT",
    "error_message": "Account does not exist"
  }
}
```

#### TD-003: Transient Failure Then Succeed Command
```json
{
  "behavior": {
    "type": "fail_transient_then_succeed",
    "transient_failures": 2,
    "error_code": "TIMEOUT",
    "error_message": "Connection timeout"
  }
}
```

#### TD-004: Transient Failure (Exhaust Retries)
```json
{
  "behavior": {
    "type": "fail_transient",
    "error_code": "SERVICE_UNAVAILABLE",
    "error_message": "External service unavailable"
  }
}
```

#### TD-005: Timeout Command
```json
{
  "behavior": {
    "type": "timeout",
    "execution_time_ms": 60000
  }
}
```

#### TD-006: Bulk Commands (Success)
```json
{
  "count": 10,
  "behavior": {
    "type": "success",
    "execution_time_ms": 50
  }
}
```

---

## 3. Test Cases

### 3.1 Module: Dashboard (TS-DASH)

| Test Case ID | Test Case Name | Priority | Type | Pre-Condition | Description | Expected Result |
|--------------|----------------|----------|------|---------------|-------------|-----------------|
| TC-DASH-001 | Dashboard Page Load | P1 | Functional | Application running | Navigate to Dashboard (/) | Dashboard loads with status cards, processing rate, and activity feed |
| TC-DASH-002 | Status Cards Display | P1 | Functional | Commands exist in system | View Dashboard | Cards show counts for Pending, In Progress, Completed, Cancelled, In TSQ |
| TC-DASH-003 | TSQ Alert Visibility | P2 | Functional | Commands in TSQ exist | View Dashboard | Red TSQ alert banner is visible with correct count |
| TC-DASH-004 | TSQ Alert Link | P2 | Functional | TSQ alert visible | Click "View TSQ" link | Navigate to /tsq page |
| TC-DASH-005 | Processing Rate Display | P2 | Functional | Worker processing commands | View Dashboard | Processing rate shows commands/min, avg time, and percentiles |
| TC-DASH-006 | Recent Activity Feed | P2 | Functional | Recent commands processed | View Dashboard | Activity feed shows recent events with timestamps |
| TC-DASH-007 | Auto-Refresh | P3 | Functional | Dashboard open for 5 seconds | Wait for auto-refresh | Stats update without page reload |
| TC-DASH-008 | Last Updated Timestamp | P3 | Functional | Dashboard loaded | View timestamp | "Last updated" shows current refresh time |

### 3.2 Module: Send Command (TS-SEND)

| Test Case ID | Test Case Name | Priority | Type | Pre-Condition | Description | Expected Result |
|--------------|----------------|----------|------|---------------|-------------|-----------------|
| TC-SEND-001 | Page Load | P1 | Functional | Application running | Navigate to /send | Send Command page loads with form |
| TC-SEND-002 | Config Display | P2 | Functional | Page loaded | View config section | Shows Visibility Timeout, Max Attempts, Backoff settings |
| TC-SEND-003 | Behavior Type Selection | P1 | Functional | Page loaded | Select each behavior type | Dropdown works, failure settings appear for failure types |
| TC-SEND-004 | Send Success Command | P1 | Functional | TD-001 prepared | Fill form with success behavior, click Send | Success message with command ID displayed |
| TC-SEND-005 | Send Permanent Failure | P1 | Functional | TD-002 prepared | Select fail_permanent, fill error code/message, send | Success message displayed, command eventually in TSQ |
| TC-SEND-006 | Send Transient Then Succeed | P1 | Functional | TD-003 prepared | Select fail_transient_then_succeed, set failures=2, send | Success message, command eventually completes |
| TC-SEND-007 | Transient Failures Input | P2 | Functional | fail_transient_then_succeed selected | View form | Transient failures input visible with default value 2 |
| TC-SEND-008 | Custom Execution Time | P2 | Functional | Page loaded | Set execution time to 500ms, send | Command takes ~500ms to process |
| TC-SEND-009 | Max Attempts Override | P2 | Functional | Page loaded | Set max attempts to 5, send with transient failures | Command allows 5 retry attempts |
| TC-SEND-010 | Custom Payload JSON | P2 | Functional | Page loaded | Enter valid JSON payload, send | Payload stored with command |
| TC-SEND-011 | Invalid JSON Payload | P1 | Functional | Page loaded | Enter invalid JSON "{bad", send | Error message: "Invalid JSON payload" |
| TC-SEND-012 | Bulk Generation | P1 | Functional | TD-006 prepared | Set count=10, select success, click Generate Bulk | Success message with created count |
| TC-SEND-013 | Bulk Max Count Validation | P2 | Functional | Page loaded | Try to set count > 1000 | Input capped at 1000 or error shown |
| TC-SEND-014 | Error Code Required | P2 | Functional | fail_permanent selected | Leave error code empty | Form submits but error_code is empty (optional) |

### 3.3 Module: Commands Browser (TS-CMD)

| Test Case ID | Test Case Name | Priority | Type | Pre-Condition | Description | Expected Result |
|--------------|----------------|----------|------|---------------|-------------|-----------------|
| TC-CMD-001 | Page Load | P1 | Functional | Application running | Navigate to /commands | Commands page loads with table |
| TC-CMD-002 | Commands Table Display | P1 | Functional | Commands exist | View page | Table shows Command ID, Type, Status, Attempts, Created, Actions |
| TC-CMD-003 | Filter by Status | P1 | Functional | Mixed status commands | Select COMPLETED status, Apply | Only COMPLETED commands shown |
| TC-CMD-004 | Filter by Domain | P2 | Functional | Commands in e2e domain | Enter "e2e", Apply | Only e2e domain commands shown |
| TC-CMD-005 | Filter by Command Type | P2 | Functional | TestCommand type exists | Enter "TestCommand", Apply | Only TestCommand type shown |
| TC-CMD-006 | Date Range Filter | P2 | Functional | Commands from different dates | Set From/To dates, Apply | Only commands in range shown |
| TC-CMD-007 | Combined Filters | P2 | Functional | Various commands exist | Apply status + domain filter | Correct intersection of filters |
| TC-CMD-008 | Clear Filters | P2 | Functional | Filters applied | Click Clear | All filters reset, all commands shown |
| TC-CMD-009 | Pagination - Next | P1 | Functional | > 20 commands exist | Click Next | Second page of results shown |
| TC-CMD-010 | Pagination - Previous | P1 | Functional | On page 2 | Click Previous | First page shown |
| TC-CMD-011 | Page Size Change | P2 | Functional | Commands exist | Change page size to 50 | 50 commands per page |
| TC-CMD-012 | Command Details Modal | P1 | Functional | Commands in table | Click row or Details button | Modal shows full command details |
| TC-CMD-013 | Modal - Command ID Display | P2 | Functional | Modal open | View Command ID | Full UUID displayed |
| TC-CMD-014 | Modal - Error Details | P2 | Functional | Command with error in modal | View modal | Error section shows code and message |
| TC-CMD-015 | Modal - Audit Link | P1 | Functional | Modal open | Click "View Audit Trail" | Navigate to audit page for command |
| TC-CMD-016 | Modal - Close Button | P2 | Functional | Modal open | Click Close or X | Modal closes |
| TC-CMD-017 | Status Badge Colors | P3 | UI | Various statuses | View table | PENDING=yellow, IN_PROGRESS=blue, COMPLETED=green, IN_TSQ=orange |
| TC-CMD-018 | No Results Message | P2 | Functional | Apply filter with no matches | View table | "No commands found" message shown |

### 3.4 Module: Troubleshooting Queue (TS-TSQ)

| Test Case ID | Test Case Name | Priority | Type | Pre-Condition | Description | Expected Result |
|--------------|----------------|----------|------|---------------|-------------|-----------------|
| TC-TSQ-001 | Page Load | P1 | Functional | Application running | Navigate to /tsq | TSQ page loads with table |
| TC-TSQ-002 | TSQ Table Display | P1 | Functional | Commands in TSQ | View page | Table shows checkbox, ID, Type, Error, Attempts, Actions |
| TC-TSQ-003 | Filter by Domain | P2 | Functional | TSQ commands in e2e | Enter domain "e2e", Apply | Only e2e domain TSQ items shown |
| TC-TSQ-004 | Clear Filter | P2 | Functional | Filter applied | Click Clear | Filter reset, all TSQ items shown |
| TC-TSQ-005 | Retry Single Command | P1 | Functional | Command in TSQ | Click retry icon | Toast: "Command re-queued", command removed from TSQ |
| TC-TSQ-006 | Cancel Single Command | P1 | Functional | Command in TSQ | Click cancel icon, confirm | Toast: "Command cancelled", command removed from TSQ |
| TC-TSQ-007 | Cancel Confirmation | P2 | Functional | Click cancel | Dialog appears | Confirmation dialog shown before cancel |
| TC-TSQ-008 | Complete Modal Open | P1 | Functional | Command in TSQ | Click complete (checkmark) icon | Complete modal opens with command ID |
| TC-TSQ-009 | Complete with Result Data | P1 | Functional | Complete modal open | Enter JSON result data, click Complete | Toast: "Command manually completed", command removed |
| TC-TSQ-010 | Complete Invalid JSON | P1 | Functional | Complete modal open | Enter invalid JSON, click Complete | Error toast: "Invalid JSON in result data" |
| TC-TSQ-011 | Complete with Notes | P2 | Functional | Complete modal open | Enter operator notes, Complete | Command completed with notes in audit |
| TC-TSQ-012 | Complete Modal Cancel | P2 | Functional | Complete modal open | Click Cancel or backdrop | Modal closes, no action taken |
| TC-TSQ-013 | Expand Details | P2 | Functional | Command in TSQ | Click expand (chevron) icon | Details row expands with error info, behavior, audit link |
| TC-TSQ-014 | Collapse Details | P2 | Functional | Details expanded | Click expand icon again | Details row collapses |
| TC-TSQ-015 | Select Single Checkbox | P2 | Functional | Commands in TSQ | Check one checkbox | Selected count updates to 1, Bulk Retry enabled |
| TC-TSQ-016 | Select All Checkbox | P2 | Functional | Multiple commands in TSQ | Check "Select All" | All checkboxes checked, count updated |
| TC-TSQ-017 | Deselect All | P2 | Functional | All selected | Uncheck "Select All" | All unchecked, count = 0, Bulk Retry disabled |
| TC-TSQ-018 | Bulk Retry | P1 | Functional | 3 commands selected | Click "Retry Selected (3)" | Toast: "3 commands re-queued", all removed from TSQ |
| TC-TSQ-019 | Empty TSQ Message | P2 | Functional | No commands in TSQ | View page | "No commands in the troubleshooting queue" shown |
| TC-TSQ-020 | Error Type Badge Color | P3 | UI | PERMANENT and TRANSIENT errors | View table | PERMANENT=red badge, TRANSIENT=yellow badge |

### 3.5 Module: Audit Trail (TS-AUDIT)

| Test Case ID | Test Case Name | Priority | Type | Pre-Condition | Description | Expected Result |
|--------------|----------------|----------|------|---------------|-------------|-----------------|
| TC-AUDIT-001 | Page Load | P1 | Functional | Application running | Navigate to /audit | Audit page loads with search form |
| TC-AUDIT-002 | Search by Command ID | P1 | Functional | Command ID known | Enter command ID, click Search | Audit events displayed for command |
| TC-AUDIT-003 | Event Timeline Display | P1 | Functional | Audit events exist | View results | Events shown in chronological order |
| TC-AUDIT-004 | Event Type Filter | P2 | Functional | Audit results shown | Select event type, Search | Only selected event types shown |
| TC-AUDIT-005 | Event Type Colors | P3 | UI | Multiple event types | View timeline | SENT=blue, STARTED=yellow, COMPLETED=green, FAILED=red |
| TC-AUDIT-006 | Event Details Expand | P2 | Functional | Audit events shown | Click on event | Event details expand showing full JSON |
| TC-AUDIT-007 | Time Duration Display | P2 | Functional | Multiple events | View timeline | Time elapsed between events shown |
| TC-AUDIT-008 | Total Duration | P2 | Functional | Complete command | View summary | Total duration from SENT to COMPLETED shown |
| TC-AUDIT-009 | Cross-Command Search | P2 | Functional | Multiple commands | Use search without command ID | Search across all commands |
| TC-AUDIT-010 | No Results Message | P2 | Functional | Search with no matches | View results | "No audit events found" message shown |

### 3.6 Module: Settings (TS-SET)

| Test Case ID | Test Case Name | Priority | Type | Pre-Condition | Description | Expected Result |
|--------------|----------------|----------|------|---------------|-------------|-----------------|
| TC-SET-001 | Page Load | P1 | Functional | Application running | Navigate to /settings | Settings page loads with configuration forms |
| TC-SET-002 | Worker Config Display | P2 | Functional | Page loaded | View Worker Configuration | Shows visibility_timeout, concurrency, poll_interval, batch_size |
| TC-SET-003 | Retry Config Display | P2 | Functional | Page loaded | View Retry Configuration | Shows max_attempts, base_delay, max_delay, backoff_multiplier |
| TC-SET-004 | Update Worker Config | P2 | Functional | Valid values entered | Change concurrency to 8, Save | Success message, config updated |
| TC-SET-005 | Update Retry Config | P2 | Functional | Valid values entered | Change max_attempts to 5, Save | Success message, config updated |
| TC-SET-006 | Validation - Negative Values | P2 | Functional | Enter -1 for concurrency | Try to save | Validation error shown |
| TC-SET-007 | Reset to Defaults | P3 | Functional | Custom values set | Click Reset | Values return to defaults |

---

## 4. End-to-End Workflow Test Cases

### 4.1 Workflow: Complete Success Lifecycle (WF-001)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to /send | Send Command page loads |
| 2 | Select "Success" behavior, set execution_time=500ms | Form populated |
| 3 | Click "Send Command" | Success message with command_id shown |
| 4 | Navigate to /commands | Commands page loads |
| 5 | Find the new command | Command shown with status PENDING or IN_PROGRESS |
| 6 | Wait 2 seconds, refresh | Command status is COMPLETED |
| 7 | Click on command row | Details modal opens |
| 8 | Click "View Audit Trail" | Audit page shows SENT, STARTED, COMPLETED events |

### 4.2 Workflow: Permanent Failure to TSQ Resolution (WF-002)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to /send | Send Command page loads |
| 2 | Select "Fail Permanent", enter error_code="TEST_ERROR" | Failure settings shown |
| 3 | Click "Send Command" | Success message with command_id shown |
| 4 | Wait 5 seconds | Command processed |
| 5 | Navigate to / (Dashboard) | TSQ alert shows count > 0 |
| 6 | Click "View TSQ" | TSQ page shows the failed command |
| 7 | Click complete (checkmark) icon | Complete modal opens |
| 8 | Enter {"manually_resolved": true}, click Complete | Toast: "Command manually completed" |
| 9 | Navigate to /audit, search for command | Shows SENT, STARTED, FAILED, MOVED_TO_TSQ, OPERATOR_COMPLETE events |

### 4.3 Workflow: Transient Failure with Retry Success (WF-003)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to /send | Send Command page loads |
| 2 | Select "Fail Transient Then Succeed", set failures=2 | Transient failures input shown |
| 3 | Click "Send Command" | Success message shown |
| 4 | Navigate to /commands | Command visible |
| 5 | Wait 10-15 seconds, refresh periodically | Command attempts increase: 1, 2, 3 |
| 6 | Final status | COMPLETED after 3rd attempt |
| 7 | View audit trail | Shows SENT, STARTED, FAILED (x2), STARTED, COMPLETED |

### 4.4 Workflow: Bulk Retry from TSQ (WF-004)

| Step | Action | Expected Result |
|------|--------|-----------------|
| 1 | Navigate to /send | Send Command page loads |
| 2 | Use Bulk Generation: count=5, behavior=fail_permanent | Form filled |
| 3 | Click "Generate Bulk Commands" | 5 commands created |
| 4 | Wait 10 seconds | Commands processed and fail |
| 5 | Navigate to /tsq | 5 commands in TSQ |
| 6 | Check "Select All" checkbox | All 5 selected, count shows 5 |
| 7 | Click "Retry Selected (5)" | Toast: "5 commands re-queued" |
| 8 | TSQ refreshes | All 5 commands removed from TSQ |

---

## 5. QTest Import Format

The test cases in this document can be imported into QTest using Excel format. Below is the column mapping:

| Excel Column | QTest Field | Notes |
|--------------|-------------|-------|
| Test Case ID | Test Case Name prefix | Use as identifier |
| Test Case Name | Name | Main test case name |
| Priority | Priority | P1=Critical, P2=High, P3=Medium |
| Type | Type | Functional, UI, etc. |
| Pre-Condition | Precondition | Test setup requirements |
| Description | Description | Steps to execute |
| Expected Result | Expected Result | Expected outcome |

### 5.1 Excel Import Template

Create an Excel file with these columns in the first row:

```
Test Case ID | Test Case Name | Priority | Type | Pre-Condition | Step # | Step Description | Expected Result
```

For multi-step test cases (workflows), each step should be a separate row with the same Test Case ID:

```
WF-001 | Complete Success Lifecycle | P1 | Workflow | Application running | 1 | Navigate to /send | Send Command page loads
WF-001 | Complete Success Lifecycle | P1 | Workflow | | 2 | Select "Success" behavior | Form populated
...
```

---

## 6. Execution Checklist

### 6.1 Pre-Execution Checklist

- [ ] Application deployed and accessible at http://localhost:5000
- [ ] PostgreSQL database running with PGMQ extension
- [ ] Database schema initialized (migrations applied)
- [ ] At least one worker process running
- [ ] Test data cleaned from previous runs
- [ ] Browser developer tools open for monitoring

### 6.2 Test Execution Log Template

| Date | Tester | Test Case ID | Status | Actual Result | Defect ID | Notes |
|------|--------|--------------|--------|---------------|-----------|-------|
| | | | Pass/Fail/Blocked | | | |

### 6.3 Defect Template

| Field | Value |
|-------|-------|
| Defect ID | DEF-XXX |
| Test Case ID | TC-XXX-XXX |
| Summary | Brief description |
| Steps to Reproduce | Numbered steps |
| Expected Result | What should happen |
| Actual Result | What actually happened |
| Severity | Critical/High/Medium/Low |
| Priority | P1/P2/P3 |
| Environment | Browser, OS, etc. |
| Attachments | Screenshots, logs |

---

## 7. Test Execution Results Summary

*To be completed after test execution*

| Module | Total | Pass | Fail | Blocked | Pass Rate |
|--------|-------|------|------|---------|-----------|
| Dashboard | | | | | |
| Send Command | | | | | |
| Commands Browser | | | | | |
| TSQ | | | | | |
| Audit Trail | | | | | |
| Settings | | | | | |
| Workflows | | | | | |
| **TOTAL** | | | | | |

---

## References

- [QTest Import Test Cases](https://www.tutorialspoint.com/qtest/qtest_import_test_cases.htm)
- [Import Test Cases Using Microsoft Excel](https://docs.tricentis.com/qtest-saas/content/manager/requirements_and_test_design/test_cases/import_test_cases_using_excel.htm)
- [Test Case Templates](https://katalon.com/resources-center/blog/test-case-template-examples)
