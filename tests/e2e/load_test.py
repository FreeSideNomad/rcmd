#!/usr/bin/env python
"""Load testing tool for the commandbus library.

This CLI tool generates and processes large numbers of commands to measure
performance and identify bottlenecks.

Usage:
    python -m tests.e2e.load_test --commands 1000 --workers 4
    python -m tests.e2e.load_test --commands 10000 --workers 8 --success-pct 90
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import sys
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from psycopg_pool import AsyncConnectionPool

from commandbus.bus import CommandBus
from commandbus.exceptions import PermanentCommandError, TransientCommandError
from commandbus.handler import HandlerRegistry
from commandbus.models import Command, CommandStatus, HandlerContext
from commandbus.worker import Worker

if TYPE_CHECKING:
    from uuid import UUID

# Track transient failures per command
_failure_counts: dict[str, int] = {}


def create_load_test_registry() -> HandlerRegistry:
    """Create a handler registry for load testing."""
    registry = HandlerRegistry()

    async def load_test_handler(cmd: Command, ctx: HandlerContext) -> dict[str, Any]:
        """Handle load test commands with configurable behavior."""
        behavior = cmd.data.get("behavior", {"type": "success"})
        behavior_type = behavior.get("type", "success")
        execution_time_ms = behavior.get("execution_time_ms", 0)
        error_code = behavior.get("error_code", "LOAD_TEST_ERROR")
        error_message = behavior.get("error_message", "Load test error")
        transient_failures = behavior.get("transient_failures", 2)

        # Simulate execution time
        if execution_time_ms > 0:
            await asyncio.sleep(execution_time_ms / 1000)

        if behavior_type == "success":
            return {"status": "success", "processed_at": time.time()}

        if behavior_type == "fail_permanent":
            raise PermanentCommandError(code=error_code, message=error_message)

        if behavior_type == "fail_transient":
            raise TransientCommandError(code=error_code, message=error_message)

        if behavior_type == "fail_transient_then_succeed":
            cmd_key = str(cmd.command_id)
            current_count = _failure_counts.get(cmd_key, 0)
            _failure_counts[cmd_key] = current_count + 1

            if current_count < transient_failures:
                raise TransientCommandError(
                    code=error_code,
                    message=f"Transient failure {current_count + 1}/{transient_failures}",
                )
            del _failure_counts[cmd_key]
            return {"status": "success", "attempts_before_success": transient_failures}

        return {"status": "success"}

    registry.register("load_test", "LoadTestCommand", load_test_handler)
    return registry


async def generate_commands(
    pool: AsyncConnectionPool,
    count: int,
    behavior_mix: dict[str, int],
    execution_time_ms: int,
) -> list[UUID]:
    """Generate load test commands."""
    command_bus = CommandBus(pool)
    command_ids: list[UUID] = []

    # Calculate behavior distribution
    total_weight = sum(behavior_mix.values())
    if total_weight == 0:
        behavior_mix = {"success": 100}
        total_weight = 100

    for i in range(count):
        command_id = uuid4()
        command_ids.append(command_id)

        # Select behavior based on distribution
        rand = (i % total_weight) + 1
        cumulative = 0
        behavior_type = "success"

        for btype, weight in behavior_mix.items():
            cumulative += weight
            if rand <= cumulative:
                behavior_type = btype
                break

        behavior: dict[str, Any] = {
            "type": behavior_type,
            "execution_time_ms": execution_time_ms,
        }
        if behavior_type == "fail_transient_then_succeed":
            behavior["transient_failures"] = 2
        elif behavior_type in ("fail_permanent", "fail_transient"):
            behavior["error_code"] = "LOAD_TEST_ERROR"

        await command_bus.send(
            domain="load_test",
            command_type="LoadTestCommand",
            command_id=command_id,
            data={"behavior": behavior},
        )

        # Print progress every 1000 commands
        if (i + 1) % 1000 == 0:
            print(f"  Generated {i + 1}/{count} commands...")

    return command_ids


async def start_workers(
    pool: AsyncConnectionPool,
    worker_count: int,
    max_attempts: int = 3,
) -> list[tuple[Worker, asyncio.Task[None]]]:
    """Start worker processes."""
    registry = create_load_test_registry()
    workers: list[tuple[Worker, asyncio.Task[None]]] = []

    for _ in range(worker_count):
        worker = Worker(
            pool,
            domain="load_test",
            registry=registry,
            visibility_timeout=30,
            concurrency=4,
            max_attempts=max_attempts,
        )
        task = asyncio.create_task(worker.run())
        workers.append((worker, task))

    # Give workers time to start
    await asyncio.sleep(0.2)
    return workers


async def stop_workers(workers: list[tuple[Worker, asyncio.Task[None]]]) -> None:
    """Stop all workers gracefully."""
    for worker, _task in workers:
        worker.stop()

    for _worker, task in workers:
        try:
            await asyncio.wait_for(task, timeout=5.0)
        except TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


async def wait_for_completion(
    pool: AsyncConnectionPool,
    command_ids: list[UUID],
    timeout: float = 300.0,
) -> dict[str, int]:
    """Wait for all commands to complete or move to TSQ."""
    command_bus = CommandBus(pool)

    completed = 0
    failed = 0
    in_tsq = 0
    pending = len(command_ids)

    start_time = time.time()
    last_report = start_time

    while pending > 0 and (time.time() - start_time) < timeout:
        completed = 0
        failed = 0
        in_tsq = 0
        pending = 0

        for cmd_id in command_ids:
            cmd = await command_bus.get_command("load_test", cmd_id)
            if cmd is None:
                pending += 1
            elif cmd.status == CommandStatus.COMPLETED:
                completed += 1
            elif cmd.status == CommandStatus.CANCELED:
                failed += 1
            elif cmd.status == CommandStatus.IN_TROUBLESHOOTING_QUEUE:
                in_tsq += 1
            else:
                pending += 1

        # Report progress every 5 seconds
        now = time.time()
        if now - last_report >= 5.0:
            elapsed = now - start_time
            rate = completed / elapsed if elapsed > 0 else 0
            print(
                f"  Progress: {completed}/{len(command_ids)} completed, "
                f"{in_tsq} in TSQ, {pending} pending ({rate:.1f}/s)"
            )
            last_report = now

        if pending > 0:
            await asyncio.sleep(0.5)

    return {
        "completed": completed,
        "failed": failed,
        "in_tsq": in_tsq,
        "pending": pending,
    }


async def cleanup_queue(pool: AsyncConnectionPool) -> None:
    """Clean up the load test queue."""
    async with pool.connection() as conn:
        # Clean up command metadata
        await conn.execute("DELETE FROM command_bus_command WHERE domain = 'load_test'")
        await conn.execute("DELETE FROM command_bus_audit WHERE domain = 'load_test'")

        # Try to clean up the queue (may not exist)
        with contextlib.suppress(Exception):
            await conn.execute("DELETE FROM pgmq.q_load_test__commands")
            await conn.execute("DELETE FROM pgmq.a_load_test__commands")


async def run_load_test(
    database_url: str,
    count: int,
    workers: int,
    delay_ms: int,
    behavior_mix: dict[str, int],
    max_attempts: int,
    cleanup: bool,
) -> None:
    """Run the load test."""
    print(f"\n{'=' * 60}")
    print("CommandBus Load Test")
    print(f"{'=' * 60}")
    print(f"Commands:     {count}")
    print(f"Workers:      {workers}")
    print(f"Delay/cmd:    {delay_ms}ms")
    print(f"Max attempts: {max_attempts}")
    print(f"Behavior:     {behavior_mix}")
    print(f"{'=' * 60}\n")

    async with AsyncConnectionPool(
        conninfo=database_url, min_size=2, max_size=workers + 5, open=False
    ) as pool:
        # Cleanup before test
        if cleanup:
            print("Cleaning up previous test data...")
            await cleanup_queue(pool)

        # Generate commands
        print(f"Generating {count} commands...")
        gen_start = time.time()
        command_ids = await generate_commands(pool, count, behavior_mix, delay_ms)
        gen_time = time.time() - gen_start
        print(f"Generated {count} commands in {gen_time:.2f}s")

        # Start workers
        print(f"\nStarting {workers} workers...")
        worker_list = await start_workers(pool, workers, max_attempts)

        # Wait for completion
        print("Processing commands...")
        process_start = time.time()
        results = await wait_for_completion(pool, command_ids)
        process_time = time.time() - process_start

        # Stop workers
        print("\nStopping workers...")
        await stop_workers(worker_list)

        # Calculate stats
        total_time = gen_time + process_time
        throughput = results["completed"] / process_time if process_time > 0 else 0

        # Print results
        print(f"\n{'=' * 60}")
        print("Load Test Results")
        print(f"{'=' * 60}")
        print(f"Total Commands:   {count}")
        print(f"Completed:        {results['completed']}")
        print(f"In TSQ:           {results['in_tsq']}")
        print(f"Failed:           {results['failed']}")
        print(f"Pending:          {results['pending']}")
        print(f"\nGeneration Time:  {gen_time:.2f}s")
        print(f"Processing Time:  {process_time:.2f}s")
        print(f"Total Time:       {total_time:.2f}s")
        print(f"Throughput:       {throughput:.1f} commands/sec")
        print(f"{'=' * 60}\n")


def main() -> None:
    """Main entry point for the load test CLI."""
    parser = argparse.ArgumentParser(
        description="Run commandbus load test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.e2e.load_test --commands 1000 --workers 4
  python -m tests.e2e.load_test --commands 10000 --workers 8 --success-pct 90
  python -m tests.e2e.load_test --commands 5000 --delay-ms 50 --no-cleanup
        """,
    )
    parser.add_argument(
        "--commands", "-c", type=int, default=1000, help="Number of commands to generate"
    )
    parser.add_argument("--workers", "-w", type=int, default=4, help="Number of worker processes")
    parser.add_argument(
        "--delay-ms", "-d", type=int, default=0, help="Execution delay per command (ms)"
    )
    parser.add_argument(
        "--success-pct",
        "-s",
        type=int,
        default=100,
        help="Percentage of commands that should succeed (0-100)",
    )
    parser.add_argument(
        "--max-attempts",
        "-m",
        type=int,
        default=3,
        help="Maximum retry attempts per command",
    )
    parser.add_argument(
        "--database-url",
        type=str,
        default=os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/commandbus",  # pragma: allowlist secret
        ),
        help="Database connection URL",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Don't clean up test data before running",
    )

    args = parser.parse_args()

    # Build behavior mix
    success_pct = max(0, min(100, args.success_pct))
    failure_pct = 100 - success_pct

    behavior_mix: dict[str, int] = {"success": success_pct}
    if failure_pct > 0:
        # Split failures between transient-then-succeed and permanent
        behavior_mix["fail_transient_then_succeed"] = failure_pct // 2
        behavior_mix["fail_permanent"] = failure_pct - (failure_pct // 2)

    try:
        asyncio.run(
            run_load_test(
                database_url=args.database_url,
                count=args.commands,
                workers=args.workers,
                delay_ms=args.delay_ms,
                behavior_mix=behavior_mix,
                max_attempts=args.max_attempts,
                cleanup=not args.no_cleanup,
            )
        )
    except KeyboardInterrupt:
        print("\nLoad test interrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()
