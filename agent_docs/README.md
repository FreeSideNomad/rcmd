# Agent Documentation

This directory contains focused documentation for LLM coding agents (Claude Code, Cursor, etc.).

These files provide **progressive disclosure** - detailed context that agents can access when needed, without bloating the main CLAUDE.md file.

## Files

| File | Purpose |
|------|---------|
| `common-pitfalls.md` | Anti-patterns and mistakes to avoid |
| `code-patterns.md` | Preferred implementation patterns |
| `testing-guide.md` | How to write and run tests |
| `database-operations.md` | Working with PostgreSQL and PGMQ |

## Usage

When working on a specific area, reference these docs:

```
Read agent_docs/testing-guide.md before writing tests
```

Or ask the agent to load them:

```
Before implementing the worker, review agent_docs/code-patterns.md
```
