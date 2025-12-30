# Command Bus

A Python library providing Command Bus abstraction over PostgreSQL + PGMQ.

> **Status**: Pre-alpha - Architecture and tooling in place, implementation in progress.

## Overview

Command Bus enables reliable command processing with:

- **At-least-once delivery** via PGMQ visibility timeout
- **Transactional guarantees** - commands sent atomically with business data
- **Retry policies** with configurable backoff
- **Troubleshooting queue** for failed commands with operator actions
- **Audit trail** for all state transitions

## Requirements

- Python 3.11+
- PostgreSQL 15+ with [PGMQ extension](https://github.com/pgmq/pgmq)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/your-org/commandbus.git
cd commandbus

# Install dependencies
make install-dev

# Start PostgreSQL with PGMQ
make docker-up

# Run tests
make test
```

## Documentation

- [Implementation Spec](docs/command-bus-python-spec.md) - Detailed design and API
- [Architecture Decisions](docs/architecture/adr/) - ADRs explaining key choices
- [Contributing](CONTRIBUTING.md) - How to contribute

## License

Apache 2.0
