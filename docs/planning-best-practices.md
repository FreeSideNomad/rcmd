# Planning Best Practices for Human-LLM Collaboration

Best practices for describing features and user stories where LLM code agents and humans collaborate on software projects.

---

## 1. Core Principles

### 1.1 Plan Before Code

Never dive straight into code generation with vague prompts. Start by:

1. **Define the problem** - What are we solving and why?
2. **Brainstorm specifications** - Use the LLM to iteratively ask questions until requirements and edge cases are clear
3. **Create a structured plan** - Break implementation into bite-sized milestones
4. **Document decisions** - Capture architecture choices and constraints

This "waterfall in 15 minutes" approach ensures both human and AI understand the goals before writing any code.

### 1.2 Human Accountability

The developer remains the senior engineer accountable for the software produced:

- Never merge code you cannot explain
- Treat LLM outputs like contributions from junior developers requiring review
- Step in when outputs seem convoluted
- Maintain your own skill development through active engagement

### 1.3 Iterative Small Chunks

Break work into small, focused iterations:

- Implement one function, fix one bug, or add one feature at a time
- Each iteration builds on previous context while remaining manageable
- Prevents "jumbled mess" outputs and allows quick course correction
- Enables granular version control (commit after each small task)

---

## 2. Specification Documents

### 2.1 Spec.md Structure

Create a comprehensive specification document before implementation:

```markdown
# Feature: [Name]

## Problem Statement
[Clear description of what problem this solves]

## Goals
- [Specific, measurable goal 1]
- [Specific, measurable goal 2]

## Non-Goals
- [What this feature explicitly will NOT do]

## Context
[Background information, related systems, constraints]

## Technical Approach
[High-level architecture and design decisions]

## Data Model
[Relevant schemas, types, interfaces]

## API Design
[Endpoints, methods, payloads]

## Security Considerations
[Authentication, authorization, data protection]

## Testing Strategy
[How this will be tested]

## Milestones
1. [First deliverable]
2. [Second deliverable]
...
```

### 2.2 Context for LLMs

Provide extensive relevant information:

- Complete codebase sections using tools like gitingest
- API documentation and technical constraints
- Examples of preferred solutions
- Explicit warnings about naive approaches to avoid
- Custom instructions via rule files (CLAUDE.md, cursor rules, etc.)

**Principle**: Don't make the AI operate on partial information.

---

## 3. Feature Documentation

### 3.1 Feature Template

```markdown
# Feature: [Name]

## Summary
[1-2 sentence description]

## Motivation
[Why this feature is needed, what user problem it solves]

## User Stories
[List of user stories - see section 4]

## Acceptance Criteria (Feature-Level)
[High-level criteria for the entire feature]

## Technical Design
### Architecture
[How this fits into the system]

### Dependencies
[External services, libraries, other features]

### Data Changes
[Database migrations, schema changes]

### API Changes
[New or modified endpoints]

## Out of Scope
[Explicitly state what is NOT included]

## Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| [Risk 1] | [High/Med/Low] | [How to address] |

## Implementation Milestones
- [ ] Milestone 1: [Description]
- [ ] Milestone 2: [Description]

## LLM Agent Notes
[Specific guidance for AI agents working on this feature]
- Preferred patterns to follow
- Anti-patterns to avoid
- Related files to reference
```

---

## 4. User Stories

### 4.1 Standard Format

Use the classic user story format with enhanced detail for LLM collaboration:

```markdown
## User Story: [Short Title]

**As a** [persona/role]
**I want** [goal/capability]
**So that** [benefit/value]

### Context
[Additional background that helps understand the story]

### Acceptance Criteria
[See section 5 for detailed formats]

### Technical Notes
[Implementation hints for developers and LLMs]

### Test Mapping
[Reference to test file or test cases]

### Dependencies
[Other stories or features this depends on]

### Priority
[Must Have / Should Have / Could Have / Won't Have]

### Estimation
[Story points or T-shirt size]
```

### 4.2 INVEST Criteria

Ensure user stories follow INVEST:

| Criterion | Description | LLM Collaboration Tip |
|-----------|-------------|----------------------|
| **I**ndependent | Can be developed separately | Helps parallelize work between human and AI |
| **N**egotiable | Open to discussion | LLM can suggest alternatives during refinement |
| **V**aluable | Provides clear benefit | Helps LLM understand "why" for better solutions |
| **E**stimable | Effort can be estimated | Smaller = more accurate AI generation |
| **S**mall | Fits in one iteration | Optimal size for LLM context windows |
| **T**estable | Has clear validation criteria | Direct mapping to test generation |

### 4.3 Story Sizing for LLM Work

Optimal story sizes for LLM collaboration:

| Size | Token Estimate | Recommended For |
|------|----------------|-----------------|
| XS | < 500 tokens | Single function, config change |
| S | 500-2000 tokens | Small feature, bug fix |
| M | 2000-5000 tokens | Module implementation |
| L | 5000-10000 tokens | Complex feature (break down) |
| XL | > 10000 tokens | Too large (must decompose) |

**Rule**: If a story exceeds M size, decompose it into smaller stories.

---

## 5. Acceptance Criteria

### 5.1 Given-When-Then Format (Gherkin)

Use BDD-style scenarios for complex behaviors:

```gherkin
Scenario: [Scenario Name]
  Given [precondition/context]
  And [additional context if needed]
  When [action/trigger]
  And [additional action if needed]
  Then [expected outcome]
  And [additional outcome if needed]
```

**Example**:

```gherkin
Scenario: User submits valid payment
  Given the user is logged in
  And the user has items in their cart totaling $50.00
  And the user has a valid payment method on file
  When the user clicks "Complete Purchase"
  Then the order is created with status "pending"
  And the payment is processed
  And the user receives an order confirmation email
  And the cart is cleared
```

### 5.2 Rule-Based Format

For simpler criteria, use a checklist:

```markdown
### Acceptance Criteria

- [ ] User can upload files up to 10MB
- [ ] Supported formats: PDF, PNG, JPG
- [ ] Upload progress is displayed
- [ ] Error message shown for invalid files
- [ ] Uploaded files appear in the gallery within 5 seconds
```

### 5.3 Mapping Criteria to Tests

Each acceptance criterion should map directly to one or more tests:

```markdown
### Acceptance Criteria with Test Mapping

| ID | Criterion | Test Type | Test Location |
|----|-----------|-----------|---------------|
| AC-1 | User can upload files up to 10MB | Integration | `tests/integration/test_upload.py::test_file_size_limit` |
| AC-2 | Error shown for files > 10MB | Unit | `tests/unit/test_validation.py::test_file_size_validation` |
| AC-3 | Progress bar updates during upload | E2E | `tests/e2e/upload.spec.ts::shows progress` |
```

### 5.4 Gherkin Best Practices

1. **One behavior per scenario** - Don't combine multiple assertions
2. **Use Background for common setup** - Reduce redundancy across scenarios
3. **Scenario Outlines for data variations** - Test multiple inputs efficiently
4. **Declarative over imperative** - Focus on "what" not "how"
5. **Business language** - Avoid technical implementation details

**Scenario Outline Example**:

```gherkin
Scenario Outline: Password validation
  Given the user is on the registration page
  When the user enters password "<password>"
  Then the validation message shows "<message>"

  Examples:
    | password | message |
    | abc | Too short (minimum 8 characters) |
    | abcdefgh | Needs at least one number |
    | abcdefg1 | Valid password |
    | ABC123def! | Valid password |
```

---

## 6. Bug Documentation

### 6.1 Bug Report Template

```markdown
## Bug: [Short Title]

### Summary
[One-line description of the bug]

### Environment
- OS: [e.g., macOS 14.0]
- Browser/Runtime: [e.g., Chrome 120, Node 20]
- Version: [e.g., v1.2.3]

### Steps to Reproduce
1. [First step]
2. [Second step]
3. [Step where bug occurs]

### Expected Behavior
[What should happen]

### Actual Behavior
[What actually happens]

### Screenshots/Logs
[Attach relevant evidence]

### Severity
[Critical / High / Medium / Low]

### Possible Cause
[If known, hypothesis about the root cause]

### Suggested Fix
[If known, approach to fix]

### Related
- Related issues: #123
- Related code: `src/module/file.py:42`

### Acceptance Criteria for Fix
- [ ] [Specific criterion 1]
- [ ] [Specific criterion 2]
- [ ] No regression in related functionality
- [ ] Test added to prevent recurrence
```

---

## 7. LLM-Specific Guidance

### 7.1 Context Files

Create project-level guidance files for LLM agents:

**CLAUDE.md / .cursorrules / etc.**

```markdown
# Project: [Name]

## Overview
[Brief project description]

## Tech Stack
- Language: Python 3.11+
- Framework: FastAPI
- Database: PostgreSQL + PGMQ
- Testing: pytest

## Code Style
- Use type hints everywhere
- Prefer composition over inheritance
- Keep functions under 30 lines
- Use dependency injection

## Patterns to Follow
- Repository pattern for data access
- Command/Query separation
- Result types for error handling

## Anti-Patterns to Avoid
- No global state
- No print statements (use logging)
- No bare except clauses
- No magic numbers

## Directory Structure
src/
  domain/       # Business logic
  api/          # HTTP handlers
  repositories/ # Data access
  services/     # Application services
tests/
  unit/
  integration/
  e2e/

## Testing Requirements
- Unit tests for all business logic
- Integration tests for repositories
- E2E tests for critical paths
- Minimum 80% coverage

## Before Submitting
- Run `make lint`
- Run `make test`
- Update relevant documentation
```

### 7.2 Story-Level LLM Instructions

Include specific guidance in each story:

```markdown
### LLM Agent Instructions

**Reference Files**:
- `src/domain/payments.py` - Similar implementation pattern
- `src/repositories/base.py` - Repository interface to follow
- `tests/unit/test_orders.py` - Test style to match

**Key Constraints**:
- Must use existing `Result` type for error handling
- Must integrate with `AuditLogger` for all state changes
- Must not introduce new dependencies

**Verification Steps**:
1. Run `pytest tests/unit/test_<feature>.py -v`
2. Run `make lint`
3. Ensure no type errors: `mypy src/`
```

---

## 8. Version Control Integration

### 8.1 Granular Commits

When working with AI agents:

- Commit after each small task (save points)
- Clear, descriptive commit messages
- Use branches for parallel AI experiments
- Quick rollback when AI suggestions introduce bugs

### 8.2 PR Description Template

```markdown
## Summary
[Brief description of changes]

## Related Issues
Closes #123
Related to #456

## Changes
- [Change 1]
- [Change 2]

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated
- [ ] Manual testing performed

## Screenshots
[If UI changes]

## Checklist
- [ ] Code follows project style guide
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No new warnings
```

---

## 9. CI/CD Integration

### 9.1 Automated Validation

Integrate these checks into your pipeline:

```yaml
# .github/workflows/validate.yml
name: Validate

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint
        run: make lint

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Test
        run: make test

  type-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Type Check
        run: make typecheck
```

### 9.2 Feedback Loop

When AI-generated code fails CI:

1. Capture failure logs
2. Feed logs back to the AI for debugging
3. Iterate until tests pass
4. Human review before merge

---

## 10. Workflow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│                    Human-LLM Collaboration Flow                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. PLAN                                                        │
│     ├── Define problem & goals                                  │
│     ├── Brainstorm with LLM (ask clarifying questions)          │
│     └── Create spec.md with milestones                          │
│                                                                 │
│  2. SPECIFY                                                     │
│     ├── Write feature documentation                             │
│     ├── Break into INVEST user stories                          │
│     └── Define acceptance criteria (Given-When-Then)            │
│                                                                 │
│  3. IMPLEMENT (per story)                                       │
│     ├── Provide context files to LLM                            │
│     ├── Generate code in small chunks                           │
│     ├── Commit after each successful change                     │
│     └── Run tests, feed failures back to LLM                    │
│                                                                 │
│  4. VERIFY                                                      │
│     ├── Human reviews all generated code                        │
│     ├── Run full test suite                                     │
│     ├── CI/CD validates automatically                           │
│     └── Mark acceptance criteria as complete                    │
│                                                                 │
│  5. ITERATE                                                     │
│     ├── Address feedback                                        │
│     ├── Refine as needed                                        │
│     └── Document lessons learned                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## References

- [My LLM Coding Workflow Going Into 2026 - Addy Osmani](https://addyo.substack.com/p/my-llm-coding-workflow-going-into)
- [Building Software in 2025: LLMs, Agents, AI - Simon Margolis](https://medium.com/google-cloud/building-software-in-2025-llms-agents-ai-and-a-real-world-workflow-85f809fe6b74)
- [Given-When-Then - Martin Fowler](https://martinfowler.com/bliki/GivenWhenThen.html)
- [Acceptance Criteria Formats - AltexSoft](https://www.altexsoft.com/blog/acceptance-criteria-purposes-formats-and-best-practices/)
- [GitHub Issue Templates Documentation](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository)
- [LLM-Based Agents for Software Engineering Survey](https://github.com/FudanSELab/Agent4SE-Paper-List)
