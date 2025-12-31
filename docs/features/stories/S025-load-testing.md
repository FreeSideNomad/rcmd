# S025 - Load Testing Support

## Parent Feature
F006 - E2E Testing & Demo Application

## User Story

**As a** developer/operator
**I want** to perform load testing with the E2E application
**So that** I can measure performance and find bottlenecks

## Context

The E2E application should support load testing scenarios where large numbers of commands are generated and processed. This helps validate the commandbus library's performance under load.

## Acceptance Criteria

### Scenario: Generate bulk commands via API
**Given** the E2E app is running
**When** I call POST /api/v1/commands/bulk with count=1000
**Then** 1000 test commands are created
**And** all are queued for processing
**And** response includes timing information

### Scenario: Multiple concurrent workers
**Given** I start 4 worker processes
**When** 1000 commands are queued
**Then** all workers process commands in parallel
**And** processing is distributed across workers

### Scenario: Measure throughput
**Given** workers are processing commands
**When** I call GET /api/v1/stats/throughput
**Then** I see commands processed per second
**And** I see average processing time
**And** I see percentile latencies (p50, p95, p99)

### Scenario: Load test with mixed behaviors
**Given** I generate commands with mixed behaviors
**When** workers process them
**Then** success, transient, and permanent failures are handled correctly
**And** metrics reflect the mixed workload

### Scenario: CLI load test command
**Given** the E2E app is available
**When** I run `python -m tests.e2e.load_test --commands 10000 --workers 4`
**Then** 10000 commands are generated and processed
**And** timing results are printed

## UI Design

### Bulk Generation (in Send Command page)

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Load Test Generation                                                           │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Command Count: [10000_____]                                                   │
│                                                                                │
│  Behavior Mix:                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐  │
│  │ ○ All Success                                                            │  │
│  │ ○ Mixed (90% success, 5% transient, 5% permanent)                       │  │
│  │ ○ Custom distribution:                                                   │  │
│  │   Success: [90]%  Transient: [5]%  Permanent: [5]%                      │  │
│  └─────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  Processing Delay: [0_____] ms (per command)                                   │
│                                                                                │
│  [Start Load Test]                                                             │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Live Metrics (in Dashboard)

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Load Test Metrics                                              [Stop Workers] │
├───────────────────────────────────────────────────────────────────────────────┤
│                                                                                │
│  Progress: ████████████████████░░░░░░░░░░░░░░░░░░░░  5,000 / 10,000 (50%)     │
│                                                                                │
│  Throughput: 245 commands/sec                                                  │
│  Avg Processing Time: 45ms                                                     │
│                                                                                │
│  Latency Percentiles:                                                          │
│    p50: 35ms    p95: 120ms    p99: 250ms                                      │
│                                                                                │
│  Active Workers: 4                                                             │
│  Queue Depth: 127                                                              │
│                                                                                │
│  Elapsed: 00:00:20    Remaining: ~00:00:20                                    │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

## API Endpoints

### POST /api/v1/commands/bulk
Generate bulk commands for load testing.

**Request:**
```json
{
  "count": 10000,
  "behavior_distribution": {
    "success": 90,
    "fail_transient_then_succeed": 5,
    "fail_permanent": 5
  },
  "delay_ms": 10
}
```

**Response:**
```json
{
  "created": 10000,
  "generation_time_ms": 1234,
  "queue_time_ms": 567
}
```

### GET /api/v1/stats/throughput
Get processing throughput metrics.

**Response:**
```json
{
  "window_seconds": 60,
  "commands_processed": 2450,
  "throughput_per_second": 40.8,
  "avg_processing_time_ms": 45,
  "p50_ms": 35,
  "p95_ms": 120,
  "p99_ms": 250,
  "active_workers": 4,
  "queue_depth": 127
}
```

### GET /api/v1/stats/load-test
Get load test progress.

**Response:**
```json
{
  "total_commands": 10000,
  "completed": 5000,
  "failed": 250,
  "in_tsq": 50,
  "pending": 4700,
  "progress_percent": 50,
  "elapsed_seconds": 20,
  "estimated_remaining_seconds": 20
}
```

## CLI Tool

```python
# tests/e2e/load_test.py

import argparse
import asyncio
import time
from uuid import uuid4

async def run_load_test(
    count: int,
    workers: int,
    delay_ms: int,
    behavior_mix: dict
):
    """Run a load test."""
    print(f"Generating {count} commands...")
    start = time.time()

    # Generate commands
    command_ids = await generate_commands(count, behavior_mix, delay_ms)
    gen_time = time.time() - start
    print(f"Generated {count} commands in {gen_time:.2f}s")

    # Start workers
    print(f"Starting {workers} workers...")
    worker_tasks = await start_workers(workers)

    # Wait for completion
    print("Processing commands...")
    await wait_for_all_complete(command_ids)

    total_time = time.time() - start
    throughput = count / total_time

    # Stop workers
    await stop_workers(worker_tasks)

    # Print results
    print(f"\n{'='*50}")
    print(f"Load Test Results")
    print(f"{'='*50}")
    print(f"Total Commands: {count}")
    print(f"Workers: {workers}")
    print(f"Total Time: {total_time:.2f}s")
    print(f"Throughput: {throughput:.1f} commands/sec")

    # Get latency stats
    stats = await get_latency_stats()
    print(f"\nLatency Percentiles:")
    print(f"  p50: {stats['p50_ms']}ms")
    print(f"  p95: {stats['p95_ms']}ms")
    print(f"  p99: {stats['p99_ms']}ms")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run commandbus load test")
    parser.add_argument("--commands", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--delay-ms", type=int, default=0)
    parser.add_argument("--success-pct", type=int, default=100)
    args = parser.parse_args()

    behavior_mix = {"success": args.success_pct}
    if args.success_pct < 100:
        remaining = 100 - args.success_pct
        behavior_mix["fail_permanent"] = remaining

    asyncio.run(run_load_test(
        count=args.commands,
        workers=args.workers,
        delay_ms=args.delay_ms,
        behavior_mix=behavior_mix
    ))
```

## Worker Concurrency Configuration

```python
# tests/e2e/app/worker.py

async def create_worker(
    pool: AsyncConnectionPool,
    domain: str = "test",
    concurrency: int = 4,
    visibility_timeout: int = 30
) -> Worker:
    """Create a worker with configurable concurrency."""
    registry = HandlerRegistry()

    @registry.handler(domain, "TestCommand")
    async def handle(cmd: Command, ctx: HandlerContext) -> dict:
        return await process_test_command(cmd, ctx)

    return Worker(
        pool,
        domain=domain,
        handler_registry=registry,
        concurrency=concurrency,
        visibility_timeout=visibility_timeout
    )

# CLI to start workers
# python -m tests.e2e.app.worker --concurrency 4
```

## Files to Create

- `tests/e2e/load_test.py` - CLI load testing tool
- `tests/e2e/app/api/routes.py` - Add /commands/bulk, /stats/throughput endpoints
- `tests/e2e/app/templates/pages/send_command.html` - Add load test section
- `tests/e2e/app/static/js/load_test.js` - Live metrics updates

## Definition of Done

- [ ] Bulk command generation API works
- [ ] Multiple workers can run concurrently
- [ ] Throughput metrics API works
- [ ] CLI load test tool works
- [ ] UI shows load test progress
- [ ] Latency percentiles calculated
- [ ] Can process 10,000 commands successfully
- [ ] Mixed behavior distribution works

## Story Size
M (2000-5000 tokens)

## Priority
Could Have

## Dependencies
- S017 - Base Infrastructure Setup
- S018 - Send Command View
- S022 - Dashboard View
