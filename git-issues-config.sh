#!/usr/bin/env bash
#
# git-issues-config.sh
#
# Creates GitHub issue templates for Feature, User Story, and Bug reports.
# Uses the gh CLI to commit templates directly to the repository.
#
# Usage:
#   ./git-issues-config.sh [--dry-run]
#
# Options:
#   --dry-run    Show what would be created without making changes
#
# Requirements:
#   - gh CLI installed and authenticated
#   - Git repository with GitHub remote
#

set -euo pipefail

# Configuration
TEMPLATE_DIR=".github/ISSUE_TEMPLATE"
DRY_RUN=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [--dry-run]"
            echo ""
            echo "Creates GitHub issue templates for Feature, User Story, and Bug reports."
            echo ""
            echo "Options:"
            echo "  --dry-run    Show what would be created without making changes"
            echo "  --help, -h   Show this help message"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $arg${NC}"
            exit 1
            ;;
    esac
done

# Check for gh CLI
if ! command -v gh &> /dev/null; then
    echo -e "${RED}Error: gh CLI is not installed.${NC}"
    echo "Install it from: https://cli.github.com/"
    exit 1
fi

# Check authentication
if ! gh auth status &> /dev/null; then
    echo -e "${RED}Error: gh CLI is not authenticated.${NC}"
    echo "Run: gh auth login"
    exit 1
fi

# Check if we're in a git repo with GitHub remote
if ! git remote -v 2>/dev/null | grep -q "github.com"; then
    echo -e "${RED}Error: Not in a Git repository with a GitHub remote.${NC}"
    exit 1
fi

echo -e "${BLUE}Creating GitHub issue templates...${NC}"
echo ""

# Create template directory
mkdir -p "$TEMPLATE_DIR"

# =============================================================================
# Template 1: Feature Request
# =============================================================================
FEATURE_TEMPLATE="$TEMPLATE_DIR/01-feature.yml"

cat > "$FEATURE_TEMPLATE" << 'EOF'
name: Feature Request
description: Propose a new feature or enhancement
title: "[Feature]: "
labels: ["feature", "needs-triage"]
body:
  - type: markdown
    attributes:
      value: |
        ## Feature Request
        Thank you for suggesting a feature! Please provide as much detail as possible.

  - type: textarea
    id: summary
    attributes:
      label: Summary
      description: A brief description of the feature (1-2 sentences)
      placeholder: "Enable users to export reports in PDF format"
    validations:
      required: true

  - type: textarea
    id: motivation
    attributes:
      label: Motivation
      description: Why is this feature needed? What problem does it solve?
      placeholder: |
        Users frequently need to share reports with stakeholders who don't have
        system access. Currently they have to screenshot or manually recreate data.
    validations:
      required: true

  - type: textarea
    id: user-stories
    attributes:
      label: User Stories
      description: Describe who benefits and how (use "As a... I want... So that..." format)
      placeholder: |
        As a project manager
        I want to export monthly reports as PDF
        So that I can share them with external stakeholders

        As an analyst
        I want to include charts in exported PDFs
        So that visual data is preserved
      render: markdown
    validations:
      required: true

  - type: textarea
    id: acceptance-criteria
    attributes:
      label: Acceptance Criteria
      description: Specific, testable conditions for this feature to be complete
      placeholder: |
        - [ ] User can click "Export PDF" button on any report
        - [ ] PDF includes all visible data and charts
        - [ ] PDF is generated within 10 seconds for standard reports
        - [ ] PDF filename includes report name and date
        - [ ] Works in Chrome, Firefox, Safari, Edge
      render: markdown
    validations:
      required: true

  - type: textarea
    id: technical-notes
    attributes:
      label: Technical Notes
      description: Any technical considerations, constraints, or implementation hints
      placeholder: |
        Consider using puppeteer or playwright for PDF generation.
        Must work with existing authentication system.
        Should integrate with the existing export dropdown menu.
      render: markdown
    validations:
      required: false

  - type: textarea
    id: out-of-scope
    attributes:
      label: Out of Scope
      description: What is explicitly NOT included in this feature?
      placeholder: |
        - Scheduled/automated exports
        - Email delivery of PDFs
        - Custom PDF templates
    validations:
      required: false

  - type: dropdown
    id: priority
    attributes:
      label: Priority
      description: How important is this feature?
      options:
        - Must Have (critical for release)
        - Should Have (important but not blocking)
        - Could Have (nice to have)
        - Won't Have (out of scope for now)
    validations:
      required: true

  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives Considered
      description: What other approaches were considered?
      placeholder: |
        - Browser print to PDF (limited formatting control)
        - Third-party service (adds external dependency)
    validations:
      required: false

  - type: textarea
    id: llm-notes
    attributes:
      label: LLM Agent Notes
      description: Specific guidance for AI coding agents working on this feature
      placeholder: |
        Reference files:
        - src/components/ExportMenu.tsx - Add new export option here
        - src/services/report.ts - Report data fetching patterns

        Patterns to follow:
        - Use existing Result<T> type for error handling
        - Follow existing button styling in Button.tsx

        Constraints:
        - Must not add dependencies > 5MB
        - Must include unit tests
      render: markdown
    validations:
      required: false
EOF

echo -e "${GREEN}Created:${NC} $FEATURE_TEMPLATE"

# =============================================================================
# Template 2: User Story
# =============================================================================
USER_STORY_TEMPLATE="$TEMPLATE_DIR/02-user-story.yml"

cat > "$USER_STORY_TEMPLATE" << 'EOF'
name: User Story
description: A specific user capability with testable acceptance criteria
title: "[Story]: "
labels: ["user-story", "needs-triage"]
body:
  - type: markdown
    attributes:
      value: |
        ## User Story
        A focused, testable piece of functionality. Stories should be small enough
        to complete in one iteration and follow INVEST criteria.

  - type: input
    id: parent-feature
    attributes:
      label: Parent Feature
      description: Link to parent feature issue (if applicable)
      placeholder: "#123"
    validations:
      required: false

  - type: textarea
    id: user-story
    attributes:
      label: User Story
      description: Standard user story format
      placeholder: |
        **As a** [type of user]
        **I want** [capability/action]
        **So that** [benefit/value]
      render: markdown
    validations:
      required: true

  - type: textarea
    id: context
    attributes:
      label: Context
      description: Additional background that helps understand this story
      placeholder: |
        This story is part of the Q1 reporting feature. Users have requested
        the ability to filter reports by date range, which is currently not
        possible.
    validations:
      required: false

  - type: textarea
    id: acceptance-criteria
    attributes:
      label: Acceptance Criteria (Given-When-Then)
      description: |
        Testable scenarios in Gherkin format. Each scenario should map to a test.
      placeholder: |
        ### Scenario: User filters by valid date range
        **Given** the user is on the reports page
        **And** there are reports from January to March
        **When** the user selects "January 1" as start date
        **And** the user selects "January 31" as end date
        **Then** only January reports are displayed
        **And** the result count shows the filtered total

        ### Scenario: User enters invalid date range
        **Given** the user is on the reports page
        **When** the user selects an end date before the start date
        **Then** an error message "End date must be after start date" is shown
        **And** the filter is not applied
      render: markdown
    validations:
      required: true

  - type: textarea
    id: test-mapping
    attributes:
      label: Test Mapping
      description: Map acceptance criteria to specific test files/cases
      placeholder: |
        | Criterion | Test Type | Test Location |
        |-----------|-----------|---------------|
        | Valid date range filter | Integration | `tests/integration/test_reports.py::test_date_filter` |
        | Invalid date range error | Unit | `tests/unit/test_validation.py::test_date_range` |
        | UI shows filtered count | E2E | `tests/e2e/reports.spec.ts::filters by date` |
      render: markdown
    validations:
      required: false

  - type: dropdown
    id: story-size
    attributes:
      label: Story Size
      description: Estimated complexity (should be S or M for LLM collaboration)
      options:
        - XS (< 500 tokens, single function)
        - S (500-2000 tokens, small feature)
        - M (2000-5000 tokens, module implementation)
        - L (5000-10000 tokens, complex - consider breaking down)
        - XL (> 10000 tokens, too large - must decompose)
    validations:
      required: true

  - type: dropdown
    id: priority
    attributes:
      label: Priority (MoSCoW)
      options:
        - Must Have
        - Should Have
        - Could Have
        - Won't Have
    validations:
      required: true

  - type: textarea
    id: dependencies
    attributes:
      label: Dependencies
      description: Other stories or components this depends on
      placeholder: |
        - Depends on #45 (Date picker component)
        - Requires API endpoint from backend team
    validations:
      required: false

  - type: textarea
    id: technical-notes
    attributes:
      label: Technical Notes
      description: Implementation hints for developers and LLM agents
      placeholder: |
        - Use existing DatePicker component from src/components/DatePicker
        - API endpoint: GET /api/reports?start={date}&end={date}
        - Follow existing filter pattern in src/hooks/useFilters.ts
      render: markdown
    validations:
      required: false

  - type: textarea
    id: llm-instructions
    attributes:
      label: LLM Agent Instructions
      description: Specific guidance for AI coding agents
      placeholder: |
        **Reference Files:**
        - `src/pages/Reports.tsx` - Add filter UI here
        - `src/hooks/useFilters.ts` - Follow this pattern
        - `tests/unit/test_filters.py` - Match test style

        **Constraints:**
        - Use existing `useQuery` hook for data fetching
        - Must work with existing Redux state
        - No new dependencies allowed

        **Verification Steps:**
        1. Run `pytest tests/unit/test_reports.py -v`
        2. Run `npm run test:e2e -- --grep "date filter"`
        3. Run `npm run lint`
      render: markdown
    validations:
      required: false

  - type: checkboxes
    id: definition-of-done
    attributes:
      label: Definition of Done
      description: Standard completion criteria
      options:
        - label: Code complete and reviewed
        - label: Unit tests written and passing
        - label: Integration tests written and passing
        - label: Acceptance criteria verified
        - label: Documentation updated (if applicable)
        - label: No regressions in related functionality
EOF

echo -e "${GREEN}Created:${NC} $USER_STORY_TEMPLATE"

# =============================================================================
# Template 3: Bug Report
# =============================================================================
BUG_TEMPLATE="$TEMPLATE_DIR/03-bug.yml"

cat > "$BUG_TEMPLATE" << 'EOF'
name: Bug Report
description: Report a bug or unexpected behavior
title: "[Bug]: "
labels: ["bug", "needs-triage"]
body:
  - type: markdown
    attributes:
      value: |
        ## Bug Report
        Please provide detailed information to help us reproduce and fix the issue.

  - type: textarea
    id: summary
    attributes:
      label: Summary
      description: A brief description of the bug (one line)
      placeholder: "Date picker crashes when selecting February 30"
    validations:
      required: true

  - type: textarea
    id: environment
    attributes:
      label: Environment
      description: Where did this occur?
      placeholder: |
        - OS: macOS 14.0 / Windows 11 / Ubuntu 22.04
        - Browser: Chrome 120 / Firefox 121 / Safari 17
        - App Version: v1.2.3
        - Node Version: 20.x (if applicable)
        - Python Version: 3.11 (if applicable)
    validations:
      required: true

  - type: textarea
    id: steps
    attributes:
      label: Steps to Reproduce
      description: Detailed steps to reproduce the behavior
      placeholder: |
        1. Go to the Reports page
        2. Click on the date picker
        3. Select February in the month dropdown
        4. Click on day 30
        5. See error in console
    validations:
      required: true

  - type: textarea
    id: expected
    attributes:
      label: Expected Behavior
      description: What should happen?
      placeholder: "Date picker should not allow selecting invalid dates"
    validations:
      required: true

  - type: textarea
    id: actual
    attributes:
      label: Actual Behavior
      description: What actually happens?
      placeholder: |
        The application crashes with error:
        "TypeError: Cannot read property 'getDate' of undefined"
        The page becomes unresponsive and requires refresh.
    validations:
      required: true

  - type: textarea
    id: logs
    attributes:
      label: Logs / Screenshots
      description: Paste error messages, stack traces, or attach screenshots
      placeholder: |
        ```
        Error: TypeError: Cannot read property 'getDate' of undefined
            at DatePicker.handleSelect (DatePicker.tsx:45)
            at onClick (DatePicker.tsx:78)
        ```
      render: markdown
    validations:
      required: false

  - type: dropdown
    id: severity
    attributes:
      label: Severity
      description: How severe is this bug?
      options:
        - Critical (system unusable, data loss)
        - High (major feature broken, no workaround)
        - Medium (feature broken, workaround exists)
        - Low (minor issue, cosmetic)
    validations:
      required: true

  - type: dropdown
    id: frequency
    attributes:
      label: Frequency
      description: How often does this occur?
      options:
        - Always (100% reproducible)
        - Often (> 50% of attempts)
        - Sometimes (< 50% of attempts)
        - Rarely (hard to reproduce)
    validations:
      required: true

  - type: textarea
    id: workaround
    attributes:
      label: Workaround
      description: Is there a temporary workaround?
      placeholder: "Users can type the date manually instead of using the picker"
    validations:
      required: false

  - type: textarea
    id: possible-cause
    attributes:
      label: Possible Cause
      description: If you have ideas about what might be causing this
      placeholder: |
        The DatePicker component doesn't validate the day against the selected month.
        Issue might be in src/components/DatePicker.tsx around line 45.
    validations:
      required: false

  - type: textarea
    id: suggested-fix
    attributes:
      label: Suggested Fix
      description: If you have ideas for how to fix this
      placeholder: |
        Add validation in handleSelect() to check if the day is valid for the month:
        - Use date-fns getDaysInMonth() to get valid day count
        - Disable invalid days in the calendar UI
    validations:
      required: false

  - type: textarea
    id: acceptance-criteria
    attributes:
      label: Acceptance Criteria for Fix
      description: How will we know the bug is fixed?
      placeholder: |
        - [ ] Invalid dates (Feb 30, Apr 31, etc.) are disabled in picker
        - [ ] Selecting a valid date works correctly
        - [ ] No console errors when interacting with date picker
        - [ ] Test added to prevent regression
      render: markdown
    validations:
      required: false

  - type: textarea
    id: related
    attributes:
      label: Related Issues / Code
      description: Links to related issues or code locations
      placeholder: |
        - Related issue: #456
        - Related code: `src/components/DatePicker.tsx:45`
    validations:
      required: false
EOF

echo -e "${GREEN}Created:${NC} $BUG_TEMPLATE"

# =============================================================================
# Template 4: Config file (template chooser configuration)
# =============================================================================
CONFIG_FILE="$TEMPLATE_DIR/config.yml"

cat > "$CONFIG_FILE" << 'EOF'
blank_issues_enabled: false
contact_links:
  - name: Documentation
    url: https://github.com/your-org/your-repo/wiki
    about: Check the documentation before opening an issue
  - name: Discussions
    url: https://github.com/your-org/your-repo/discussions
    about: Ask questions and discuss ideas
EOF

echo -e "${GREEN}Created:${NC} $CONFIG_FILE"

# =============================================================================
# Summary and next steps
# =============================================================================
echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}Issue templates created successfully!${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Templates created:"
echo "  - $FEATURE_TEMPLATE"
echo "  - $USER_STORY_TEMPLATE"
echo "  - $BUG_TEMPLATE"
echo "  - $CONFIG_FILE"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}DRY RUN: No changes committed.${NC}"
    echo ""
    echo "To apply these changes, run without --dry-run:"
    echo "  $0"
    exit 0
fi

echo -e "${BLUE}Next steps:${NC}"
echo ""
echo "1. Review the templates:"
echo "   cat $TEMPLATE_DIR/*.yml"
echo ""
echo "2. Update config.yml with your repository URLs:"
echo "   edit $CONFIG_FILE"
echo ""
echo "3. Create required labels (if they don't exist):"
echo "   gh label create feature --color 0E8A16 --description 'New feature request'"
echo "   gh label create user-story --color 1D76DB --description 'User story'"
echo "   gh label create bug --color D73A4A --description 'Something is not working'"
echo "   gh label create needs-triage --color FBCA04 --description 'Needs triage'"
echo ""
echo "4. Commit and push the templates:"
echo "   git add $TEMPLATE_DIR"
echo "   git commit -m 'Add GitHub issue templates for features, stories, and bugs'"
echo "   git push"
echo ""
echo "5. Test by creating a new issue:"
echo "   gh issue create"
echo ""
echo -e "${GREEN}Done!${NC}"
