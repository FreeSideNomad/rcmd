# S068: Cross-Domain TSQ Helpers

## User Story

As an operator or UI consumer, I want `TroubleshootingQueue` to expose cross-domain listing helpers so that I can query all commands in the troubleshooting queue (not just `e2e`) without reimplementing SQL or knowing individual domains.

## Acceptance Criteria

### AC1: Enumerate TSQ Domains
- Given commands from multiple domains sit in TSQ
- When I call `TroubleshootingQueue.list_domains()`
- Then I receive the set of domains with TSQ entries (sorted alphabetically)

### AC2: Aggregate TSQ Items Without Filter
- Given I call `list_all_troubleshooting(limit, offset)` with no domain
- When there are commands under both `e2e` and `reporting`
- Then the helper iterates across domains, respects pagination, and returns merged `TroubleshootingItem`s plus total and all command IDs

### AC3: Domain-Specific Listing Still Works
- Given I call `list_all_troubleshooting(limit, offset, domain="reporting")`
- When only reporting commands are needed
- Then the helper delegates to the existing per-domain query and matches prior behavior

### AC4: FastAPI Uses Helper
- Given the `/api/v1/tsq` route
- When the helper exists
- Then the route simply calls it instead of duplicating SQL (and TSQ actions auto-detect command domain)

## Notes

- Added `get_command_domain()` to avoid copying SQL across API handlers.
- API response now includes multi-domain entries, allowing the E2E UI to display reporting-domain failures.
