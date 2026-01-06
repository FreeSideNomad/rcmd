"""E2E API routes - FastAPI endpoints with native async."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from psycopg.types.json import Json

from commandbus import BatchCommand
from commandbus.models import SendRequest

from ..dependencies import TSQ, Bus, Pool
from ..models import TestCommandRepository
from .schemas import (
    ActivityEvent,
    AuditEvent,
    AuditSearchEvent,
    AuditSearchResponse,
    AuditTrailResponse,
    BatchCommandResponse,
    BatchCommandsListResponse,
    BatchDetailResponse,
    BatchListResponse,
    BatchSummary,
    BulkCreateRequest,
    BulkCreateResponse,
    CommandListResponse,
    CommandResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    CreateBatchRequest,
    CreateBatchResponse,
    CreateCommandRequest,
    CreateCommandResponse,
    HealthResponse,
    LoadTestResponse,
    ProcessingRate,
    RecentActivityResponse,
    ReplyMessage,
    ReplyQueueResponse,
    ReplySummaryListResponse,
    ReplySummaryResponse,
    RetryConfigSchema,
    StatsOverviewResponse,
    ThroughputResponse,
    TSQActionResponse,
    TSQBulkRetryRequest,
    TSQBulkRetryResponse,
    TSQCommandResponse,
    TSQListResponse,
    TSQOperatorRequest,
    WorkerConfigSchema,
)

api_router = APIRouter()

# Domain used for E2E demo commands
E2E_DOMAIN = "e2e"


# =============================================================================
# Command Endpoints
# =============================================================================


@api_router.post("/commands", response_model=CreateCommandResponse, status_code=201)
async def create_command(
    request: CreateCommandRequest, bus: Bus, pool: Pool
) -> CreateCommandResponse:
    """Create a single test command."""
    command_id = uuid4()
    behavior = request.behavior.model_dump()

    # Insert into test_command table (handler reads behavior from here)
    repo = TestCommandRepository(pool)
    await repo.create(command_id, behavior, request.payload)

    await bus.send(
        domain=E2E_DOMAIN,
        command_type="TestCommand",
        command_id=command_id,
        data={"behavior": behavior, "payload": request.payload},
        max_attempts=request.max_attempts,
        reply_to=request.reply_to,
    )

    return CreateCommandResponse(
        command_id=command_id,
        behavior=request.behavior,
        payload=request.payload,
        reply_to=request.reply_to,
        message="Command created and queued",
    )


@api_router.post("/commands/bulk", response_model=BulkCreateResponse, status_code=201)
async def create_bulk_commands(
    request: BulkCreateRequest, bus: Bus, pool: Pool
) -> BulkCreateResponse:
    """Create multiple test commands with probabilistic behavior.

    Uses batch operations for efficient bulk creation:
    - bus.send_batch() for PGMQ messages and command metadata
    - repo.create_batch() for test command records

    All commands share the same probabilistic behavior configuration,
    but each command's actual behavior is determined at execution time
    by independent random rolls.
    """
    start_time = time.time()

    count = request.count
    repo = TestCommandRepository(pool)
    behavior = request.behavior.model_dump()

    # Build all commands
    send_requests: list[SendRequest] = []
    test_commands: list[tuple[UUID, dict[str, Any], dict[str, Any]]] = []

    for _ in range(count):
        cmd_id = uuid4()

        # Prepare test command record
        test_commands.append((cmd_id, behavior, {}))

        # Prepare send request
        send_requests.append(
            SendRequest(
                domain=E2E_DOMAIN,
                command_type="TestCommand",
                command_id=cmd_id,
                data={"behavior": behavior},
                max_attempts=request.max_attempts,
            )
        )

    # Batch insert test commands
    await repo.create_batch(test_commands)

    # Batch send to command bus
    batch_result = await bus.send_batch(send_requests)

    generation_time_ms = int((time.time() - start_time) * 1000)

    # Get first 100 command IDs from results
    command_ids = [r.command_id for r in batch_result.results[:100]]

    return BulkCreateResponse(
        created=batch_result.total_commands,
        command_ids=[str(cid) for cid in command_ids],
        total_command_ids=batch_result.total_commands,
        generation_time_ms=generation_time_ms,
        queue_time_ms=int((time.time() - start_time) * 1000),
        message=f"{batch_result.total_commands} commands in {batch_result.chunks_processed} chunks",
    )


@api_router.get("/commands", response_model=CommandListResponse)
async def list_commands(
    pool: Pool,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> CommandListResponse:
    """Query commands with filters."""
    limit = min(limit, 100)

    async with pool.connection() as conn:
        query = """
            SELECT command_id, domain, command_type, status, attempts, max_attempts,
                   created_at, updated_at, last_error_code, last_error_msg, correlation_id
            FROM commandbus.command
            WHERE domain = %s
        """
        params: list[Any] = [E2E_DOMAIN]

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        async with conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

            # Get total count
            count_query = "SELECT COUNT(*) FROM commandbus.command WHERE domain = %s"
            count_params: list[Any] = [E2E_DOMAIN]
            if status:
                count_query += " AND status = %s"
                count_params.append(status)
            await cur.execute(count_query, count_params)
            total_row = await cur.fetchone()
            total = total_row[0] if total_row else 0

    commands = [
        CommandResponse(
            command_id=row[0],
            domain=row[1],
            command_type=row[2],
            status=row[3],
            attempts=row[4],
            max_attempts=row[5],
            created_at=row[6],
            updated_at=row[7],
            last_error_code=row[8],
            last_error_message=row[9],
            correlation_id=row[10],
        )
        for row in rows
    ]

    return CommandListResponse(
        commands=commands,
        total=total,
        limit=limit,
        offset=offset,
    )


@api_router.get("/commands/{command_id}", response_model=CommandResponse)
async def get_command(command_id: UUID, bus: Bus) -> CommandResponse:
    """Get single command details."""
    cmd = await bus.get_command(E2E_DOMAIN, command_id)

    if cmd is None:
        raise HTTPException(status_code=404, detail="Command not found")

    return CommandResponse(
        command_id=cmd.command_id,
        domain=cmd.domain,
        command_type=cmd.command_type,
        status=cmd.status.value,
        attempts=cmd.attempts,
        max_attempts=cmd.max_attempts,
        created_at=cmd.created_at,
        updated_at=cmd.updated_at,
        correlation_id=cmd.correlation_id,
        last_error_code=cmd.last_error_code,
        last_error_message=cmd.last_error_msg,
    )


# =============================================================================
# Stats Endpoints
# =============================================================================


@api_router.get("/stats/overview", response_model=StatsOverviewResponse)
async def stats_overview(pool: Pool) -> StatsOverviewResponse:
    """Get dashboard statistics from real database."""
    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            # Get status counts
            await cur.execute(
                """
                SELECT status, COUNT(*) as count
                FROM commandbus.command
                WHERE domain = %s
                GROUP BY status
            """,
                (E2E_DOMAIN,),
            )
            rows = await cur.fetchall()

            status_counts = {
                "PENDING": 0,
                "IN_PROGRESS": 0,
                "COMPLETED": 0,
                "CANCELLED": 0,
                "IN_TSQ": 0,
            }
            for row in rows:
                status_name = row[0]
                if status_name == "IN_TROUBLESHOOTING_QUEUE":
                    status_counts["IN_TSQ"] = row[1]
                elif status_name in status_counts:
                    status_counts[status_name] = row[1]

            # Get processing rate from recent completions
            await cur.execute(
                """
                SELECT COUNT(*) as completed_last_minute
                FROM commandbus.audit
                WHERE domain = %s
                  AND event_type = 'COMPLETED'
                  AND ts > NOW() - INTERVAL '1 minute'
            """,
                (E2E_DOMAIN,),
            )
            rate_row = await cur.fetchone()
            per_minute = rate_row[0] if rate_row else 0

            # Get average processing time from audit events
            await cur.execute(
                """
                SELECT
                    EXTRACT(EPOCH FROM (MAX(ts) - MIN(ts))) * 1000 as duration_ms
                FROM commandbus.audit
                WHERE domain = %s
                  AND command_id IN (
                      SELECT DISTINCT command_id FROM commandbus.audit
                      WHERE domain = %s AND event_type = 'COMPLETED'
                        AND ts > NOW() - INTERVAL '5 minutes'
                      LIMIT 100
                  )
                GROUP BY command_id
            """,
                (E2E_DOMAIN, E2E_DOMAIN),
            )
            durations = [row[0] for row in await cur.fetchall() if row[0]]

            avg_time_ms = int(sum(durations) / len(durations)) if durations else 0
            sorted_durations = sorted(durations) if durations else [0]
            n = len(sorted_durations)
            p50_ms = int(sorted_durations[n // 2]) if sorted_durations else 0
            p95_ms = int(sorted_durations[int(n * 0.95)]) if n > 1 else p50_ms
            p99_ms = int(sorted_durations[int(n * 0.99)]) if n > 1 else p95_ms

            return StatsOverviewResponse(
                status_counts=status_counts,
                processing_rate=ProcessingRate(
                    per_minute=per_minute,
                    avg_time_ms=avg_time_ms,
                    p50_ms=p50_ms,
                    p95_ms=p95_ms,
                    p99_ms=p99_ms,
                ),
                recent_change={
                    "PENDING": 0,
                    "COMPLETED": per_minute,
                },
            )
    except Exception as e:
        return StatsOverviewResponse(
            status_counts={
                "PENDING": 0,
                "IN_PROGRESS": 0,
                "COMPLETED": 0,
                "CANCELLED": 0,
                "IN_TSQ": 0,
            },
            processing_rate=ProcessingRate(
                per_minute=0, avg_time_ms=0, p50_ms=0, p95_ms=0, p99_ms=0
            ),
            recent_change={"PENDING": 0, "COMPLETED": 0},
            error=str(e),
        )


@api_router.get("/stats/recent-activity", response_model=RecentActivityResponse)
async def recent_activity(pool: Pool, limit: int = 10) -> RecentActivityResponse:
    """Get recent activity feed from audit table."""
    limit = min(limit, 50)

    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT a.command_id, a.event_type, a.ts, c.command_type
                FROM commandbus.audit a
                LEFT JOIN commandbus.command c
                    ON a.command_id = c.command_id AND a.domain = c.domain
                WHERE a.domain = %s
                ORDER BY a.ts DESC
                LIMIT %s
            """,
                (E2E_DOMAIN, limit),
            )
            rows = await cur.fetchall()

            events = []
            for row in rows:
                cmd_type = row[3] or "TestCommand"
                event_type = row[1]
                summary_map = {
                    "SENT": f"{cmd_type} queued",
                    "STARTED": f"{cmd_type} processing",
                    "COMPLETED": f"{cmd_type} completed",
                    "FAILED": f"{cmd_type} failed",
                    "MOVED_TO_TSQ": f"{cmd_type} moved to TSQ",
                    "OPERATOR_RETRY": f"{cmd_type} retried by operator",
                    "OPERATOR_CANCEL": f"{cmd_type} cancelled by operator",
                    "OPERATOR_COMPLETE": f"{cmd_type} completed by operator",
                }
                events.append(
                    ActivityEvent(
                        command_id=str(row[0]),
                        event_type=event_type,
                        timestamp=row[2].isoformat() if row[2] else None,
                        summary=summary_map.get(event_type, f"{cmd_type} {event_type.lower()}"),
                    )
                )

            return RecentActivityResponse(events=events)
    except Exception as e:
        return RecentActivityResponse(events=[], error=str(e))


@api_router.get("/stats/throughput", response_model=ThroughputResponse)
async def stats_throughput(pool: Pool, window: int = 60) -> ThroughputResponse:
    """Get processing throughput metrics."""
    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            # Get commands completed in window
            await cur.execute(
                """
                    SELECT COUNT(*) FROM commandbus.audit
                    WHERE domain = %s
                      AND event_type = 'COMPLETED'
                      AND ts > NOW() - INTERVAL '%s seconds'
                """,
                (E2E_DOMAIN, window),
            )
            row = await cur.fetchone()
            commands_processed = row[0] if row else 0

            # Get queue depth
            await cur.execute(
                """
                    SELECT COUNT(*) FROM commandbus.command
                    WHERE domain = %s AND status = 'PENDING'
                """,
                (E2E_DOMAIN,),
            )
            queue_row = await cur.fetchone()
            queue_depth = queue_row[0] if queue_row else 0

            return ThroughputResponse(
                window_seconds=window,
                commands_processed=commands_processed,
                throughput_per_second=round(commands_processed / window, 1) if window > 0 else 0,
                avg_processing_time_ms=0,
                p50_ms=0,
                p95_ms=0,
                p99_ms=0,
                active_workers=0,
                queue_depth=queue_depth,
            )
    except Exception as e:
        return ThroughputResponse(
            window_seconds=window,
            commands_processed=0,
            throughput_per_second=0,
            avg_processing_time_ms=0,
            p50_ms=0,
            p95_ms=0,
            p99_ms=0,
            active_workers=0,
            queue_depth=0,
            error=str(e),
        )


@api_router.get("/stats/load-test", response_model=LoadTestResponse)
async def stats_load_test(pool: Pool, total: int = 10000) -> LoadTestResponse:
    """Get load test progress."""
    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    SELECT status, COUNT(*) FROM commandbus.command
                    WHERE domain = %s
                    GROUP BY status
                """,
                (E2E_DOMAIN,),
            )
            rows = await cur.fetchall()

            counts: dict[str, int] = {}
            for row in rows:
                counts[row[0]] = row[1]

            completed = counts.get("COMPLETED", 0)
            failed = counts.get("CANCELLED", 0)
            in_tsq = counts.get("IN_TROUBLESHOOTING_QUEUE", 0)
            pending = counts.get("PENDING", 0) + counts.get("IN_PROGRESS", 0)
            total_actual = completed + failed + in_tsq + pending

            return LoadTestResponse(
                total_commands=total_actual if total_actual > 0 else total,
                completed=completed,
                failed=failed,
                in_tsq=in_tsq,
                pending=pending,
                progress_percent=round((completed / total_actual) * 100, 1)
                if total_actual > 0
                else 0,
                elapsed_seconds=0,
                estimated_remaining_seconds=0,
                throughput_per_second=0,
            )
    except Exception as e:
        return LoadTestResponse(
            total_commands=0,
            completed=0,
            failed=0,
            in_tsq=0,
            pending=0,
            progress_percent=0,
            elapsed_seconds=0,
            estimated_remaining_seconds=0,
            throughput_per_second=0,
            error=str(e),
        )


# =============================================================================
# Health & Config Endpoints
# =============================================================================


@api_router.get("/health", response_model=HealthResponse)
async def health(pool: Pool) -> HealthResponse:
    """Health check endpoint."""
    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT 1")
        return HealthResponse(status="ok", database="connected")
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@api_router.get("/config", response_model=ConfigResponse)
async def get_config(pool: Pool) -> ConfigResponse:
    """Get current configuration from database."""
    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT key, value FROM e2e.config")
            rows = await cur.fetchall()
            config: dict[str, Any] = {}
            for row in rows:
                config[row[0]] = row[1]

            return ConfigResponse(
                worker=WorkerConfigSchema(**(config.get("worker", {}))),
                retry=RetryConfigSchema(**(config.get("retry", {}))),
            )
    except Exception as e:
        return ConfigResponse(
            worker=WorkerConfigSchema(),
            retry=RetryConfigSchema(),
            error=str(e),
        )


@api_router.put("/config", response_model=ConfigUpdateResponse)
async def update_config(request: ConfigUpdateRequest, pool: Pool) -> ConfigUpdateResponse:
    """Update configuration in database."""
    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            if request.worker:
                await cur.execute(
                    """
                        INSERT INTO e2e.config (key, value, updated_at)
                        VALUES ('worker', %s, NOW())
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                    (Json(request.worker.model_dump()),),
                )
            if request.retry:
                await cur.execute(
                    """
                        INSERT INTO e2e.config (key, value, updated_at)
                        VALUES ('retry', %s, NOW())
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                    (Json(request.retry.model_dump()),),
                )

        return ConfigUpdateResponse(status="ok", config=request)
    except Exception as e:
        return ConfigUpdateResponse(status="error", error=str(e))


# =============================================================================
# Troubleshooting Queue (TSQ) Endpoints
# =============================================================================


@api_router.get("/tsq", response_model=TSQListResponse)
async def list_tsq_commands(
    tsq: TSQ, pool: Pool, limit: int = 100, offset: int = 0
) -> TSQListResponse:
    """List commands in troubleshooting queue."""
    limit = min(limit, 100)

    try:
        commands = await tsq.list_troubleshooting(E2E_DOMAIN, limit=limit, offset=offset)

        result = [
            TSQCommandResponse(
                command_id=str(cmd.command_id),
                domain=cmd.domain,
                command_type=cmd.command_type,
                status="IN_TSQ",
                attempts=cmd.attempts,
                max_attempts=cmd.max_attempts,
                last_error_type=cmd.last_error_type,
                last_error_code=cmd.last_error_code,
                last_error_message=cmd.last_error_msg,
                created_at=cmd.created_at.isoformat() if cmd.created_at else None,
                updated_at=cmd.updated_at.isoformat() if cmd.updated_at else None,
            )
            for cmd in commands
        ]

        # Get total count and all command IDs for "select all" feature
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    SELECT command_id FROM commandbus.command
                    WHERE domain = %s AND status = 'IN_TROUBLESHOOTING_QUEUE'
                    ORDER BY created_at DESC
                """,
                (E2E_DOMAIN,),
            )
            rows = await cur.fetchall()
            all_command_ids = [str(row[0]) for row in rows]
            total = len(all_command_ids)

        return TSQListResponse(
            commands=result,
            total=total,
            limit=limit,
            offset=offset,
            all_command_ids=all_command_ids,
        )
    except Exception as e:
        return TSQListResponse(commands=[], total=0, limit=limit, offset=offset, error=str(e))


@api_router.post("/tsq/{command_id}/retry", response_model=TSQActionResponse)
async def retry_tsq_command(
    command_id: str, tsq: TSQ, request: TSQOperatorRequest | None = None
) -> TSQActionResponse:
    """Retry a command from TSQ."""
    operator = request.operator if request else "e2e-ui"

    try:
        await tsq.operator_retry(E2E_DOMAIN, UUID(command_id), operator=operator)
        return TSQActionResponse(
            command_id=command_id,
            status="PENDING",
            message="Command re-queued for processing",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@api_router.post("/tsq/{command_id}/cancel", response_model=TSQActionResponse)
async def cancel_tsq_command(
    command_id: str, tsq: TSQ, request: TSQOperatorRequest | None = None
) -> TSQActionResponse:
    """Cancel a command in TSQ."""
    operator = request.operator if request else "e2e-ui"
    reason = request.reason if request else "Cancelled via UI"

    try:
        await tsq.operator_cancel(E2E_DOMAIN, UUID(command_id), operator=operator, reason=reason)
        return TSQActionResponse(
            command_id=command_id,
            status="CANCELLED",
            message="Command cancelled",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@api_router.post("/tsq/{command_id}/complete", response_model=TSQActionResponse)
async def complete_tsq_command(
    command_id: str, tsq: TSQ, request: TSQOperatorRequest | None = None
) -> TSQActionResponse:
    """Manually complete a command in TSQ."""
    operator = request.operator if request else "e2e-ui"
    result_data = request.result_data if request else None

    try:
        await tsq.operator_complete(
            E2E_DOMAIN,
            UUID(command_id),
            result_data=result_data,
            operator=operator,
        )
        return TSQActionResponse(
            command_id=command_id,
            status="COMPLETED",
            result_data=result_data,
            operator=operator,
            message="Command manually completed",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@api_router.post("/tsq/bulk-retry", response_model=TSQBulkRetryResponse)
async def bulk_retry_tsq_commands(request: TSQBulkRetryRequest, tsq: TSQ) -> TSQBulkRetryResponse:
    """Retry multiple commands from TSQ."""
    retried = 0
    errors = []
    for cmd_id in request.command_ids:
        try:
            await tsq.operator_retry(E2E_DOMAIN, UUID(cmd_id), operator=request.operator)
            retried += 1
        except Exception as e:
            errors.append(f"{cmd_id}: {e}")
            if len(errors) <= 3:  # Only log first few errors
                import logging

                logging.error(f"Failed to retry {cmd_id}: {e}")

    error_msg = f" (errors: {errors[0]})" if errors else None
    return TSQBulkRetryResponse(
        retried=retried,
        command_ids=request.command_ids,
        message=f"{retried} commands re-queued for processing",
        error=error_msg,
    )


# =============================================================================
# Audit Trail Endpoints
# =============================================================================


@api_router.get("/audit/{command_id}", response_model=AuditTrailResponse)
async def get_audit_trail(command_id: str, pool: Pool) -> AuditTrailResponse:
    """Get audit trail for a specific command."""
    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    SELECT audit_id, event_type, ts, details_json
                    FROM commandbus.audit
                    WHERE domain = %s AND command_id = %s
                    ORDER BY ts ASC
                """,
                (E2E_DOMAIN, UUID(command_id)),
            )
            rows = await cur.fetchall()

            events = [
                AuditEvent(
                    id=row[0],
                    event_type=row[1],
                    timestamp=row[2].isoformat() if row[2] else None,
                    details=row[3] or {},
                )
                for row in rows
            ]

            # Calculate duration
            total_duration_ms = 0
            if len(events) >= 2:
                first_ts = datetime.fromisoformat(
                    events[0].timestamp.replace("Z", "+00:00") if events[0].timestamp else ""
                )
                last_ts = datetime.fromisoformat(
                    events[-1].timestamp.replace("Z", "+00:00") if events[-1].timestamp else ""
                )
                total_duration_ms = int((last_ts - first_ts).total_seconds() * 1000)

            return AuditTrailResponse(
                command_id=command_id,
                events=events,
                total_duration_ms=total_duration_ms,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid command ID format") from e
    except Exception as e:
        return AuditTrailResponse(
            command_id=command_id, events=[], total_duration_ms=0, error=str(e)
        )


@api_router.get("/audit/search", response_model=AuditSearchResponse)
async def search_audit_events(
    pool: Pool,
    event_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> AuditSearchResponse:
    """Search audit events across commands."""
    limit = min(limit, 200)

    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            query = """
                SELECT a.audit_id, a.command_id, a.event_type, a.ts,
                       a.details_json, c.command_type
                FROM commandbus.audit a
                LEFT JOIN commandbus.command c
                    ON a.command_id = c.command_id AND a.domain = c.domain
                WHERE a.domain = %s
            """
            params: list[Any] = [E2E_DOMAIN]

            if event_type:
                query += " AND a.event_type = %s"
                params.append(event_type)

            query += " ORDER BY a.ts DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            await cur.execute(query, params)
            rows = await cur.fetchall()

            events = [
                AuditSearchEvent(
                    id=row[0],
                    command_id=str(row[1]),
                    event_type=row[2],
                    timestamp=row[3].isoformat() if row[3] else None,
                    details=row[4] or {},
                    domain=E2E_DOMAIN,
                    command_type=row[5] or "TestCommand",
                )
                for row in rows
            ]

            # Get total count
            count_query = "SELECT COUNT(*) FROM commandbus.audit WHERE domain = %s"
            count_params: list[Any] = [E2E_DOMAIN]
            if event_type:
                count_query += " AND event_type = %s"
                count_params.append(event_type)
            await cur.execute(count_query, count_params)
            total_row = await cur.fetchone()
            total = total_row[0] if total_row else 0

            return AuditSearchResponse(
                events=events,
                total=total,
                limit=limit,
                offset=offset,
            )
    except Exception as e:
        return AuditSearchResponse(events=[], total=0, limit=limit, offset=offset, error=str(e))


# =============================================================================
# Batch Endpoints
# =============================================================================


@api_router.post("/batches", response_model=CreateBatchResponse, status_code=201)
async def create_batch(request: CreateBatchRequest, bus: Bus, pool: Pool) -> CreateBatchResponse:
    """Create a new batch with test commands."""
    repo = TestCommandRepository(pool)
    behavior = request.behavior.model_dump()

    # Build batch commands
    # Generate batch_id upfront so we can use it as correlation_id for reply tracking
    batch_id = uuid4()

    batch_commands: list[BatchCommand] = []
    test_commands: list[tuple[UUID, dict[str, Any], dict[str, Any]]] = []

    for _ in range(request.command_count):
        cmd_id = uuid4()
        batch_commands.append(
            BatchCommand(
                command_type="TestCommand",
                command_id=cmd_id,
                data={"behavior": behavior},
                max_attempts=request.max_attempts,
                reply_to=request.reply_to,
                # Use batch_id as correlation_id when reply_to is set for reply tracking
                correlation_id=batch_id if request.reply_to else None,
            )
        )
        test_commands.append((cmd_id, behavior, {}))

    # Create test command records
    await repo.create_batch(test_commands)

    # Create batch via CommandBus
    result = await bus.create_batch(
        domain=E2E_DOMAIN,
        commands=batch_commands,
        name=request.name,
        batch_id=batch_id,
    )

    # Create batch summary if reply_to is configured
    if request.reply_to:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO e2e.batch_summary (batch_id, domain, total_expected)
                VALUES (%s, %s, %s)
                ON CONFLICT (batch_id) DO NOTHING
                """,
                (result.batch_id, E2E_DOMAIN, result.total_commands),
            )

    return CreateBatchResponse(
        batch_id=result.batch_id,
        total_commands=result.total_commands,
        message=f"Batch created with {result.total_commands} commands",
    )


@api_router.get("/batches", response_model=BatchListResponse)
async def list_batches(
    pool: Pool,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> BatchListResponse:
    """List batches with optional status filter."""
    limit = min(limit, 100)

    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            query = """
                SELECT batch_id, name, status, total_count, completed_count,
                       canceled_count, in_troubleshooting_count, created_at
                FROM commandbus.batch
                WHERE domain = %s
            """
            params: list[Any] = [E2E_DOMAIN]

            if status:
                query += " AND status = %s"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            await cur.execute(query, params)
            rows = await cur.fetchall()

            # Get total count
            count_query = "SELECT COUNT(*) FROM commandbus.batch WHERE domain = %s"
            count_params: list[Any] = [E2E_DOMAIN]
            if status:
                count_query += " AND status = %s"
                count_params.append(status)
            await cur.execute(count_query, count_params)
            total_row = await cur.fetchone()
            total = total_row[0] if total_row else 0

        batches = []
        for row in rows:
            total_count = row[3] or 0
            completed = row[4] or 0
            progress = (completed / total_count * 100) if total_count > 0 else 0
            batches.append(
                BatchSummary(
                    batch_id=row[0],
                    name=row[1],
                    status=row[2],
                    total_count=total_count,
                    completed_count=completed,
                    failed_count=0,  # Not tracked in database schema
                    canceled_count=row[5] or 0,
                    in_troubleshooting_count=row[6] or 0,
                    progress_percent=round(progress, 1),
                    created_at=row[7],
                )
            )

        return BatchListResponse(
            batches=batches,
            total=total,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        return BatchListResponse(batches=[], total=0, limit=limit, offset=offset, error=str(e))


@api_router.get("/batches/{batch_id}", response_model=BatchDetailResponse)
async def get_batch(batch_id: UUID, bus: Bus) -> BatchDetailResponse:
    """Get batch details."""
    batch = await bus.get_batch(E2E_DOMAIN, batch_id)

    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    total_count = batch.total_count or 0
    completed = batch.completed_count or 0
    progress = (completed / total_count * 100) if total_count > 0 else 0

    return BatchDetailResponse(
        batch_id=batch.batch_id,
        name=batch.name,
        status=batch.status.value,
        total_count=total_count,
        completed_count=completed,
        failed_count=0,  # Not tracked in BatchMetadata model
        canceled_count=batch.canceled_count or 0,
        in_troubleshooting_count=batch.in_troubleshooting_count or 0,
        progress_percent=round(progress, 1),
        created_at=batch.created_at,
        started_at=batch.started_at,
        completed_at=batch.completed_at,
        custom_data=batch.custom_data,
    )


@api_router.get("/batches/{batch_id}/commands", response_model=BatchCommandsListResponse)
async def get_batch_commands(
    batch_id: UUID,
    pool: Pool,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> BatchCommandsListResponse:
    """Get commands belonging to a batch."""
    limit = min(limit, 100)

    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            query = """
                SELECT command_id, command_type, status, attempts, max_attempts,
                       created_at, last_error_code, last_error_msg
                FROM commandbus.command
                WHERE domain = %s AND batch_id = %s
            """
            params: list[Any] = [E2E_DOMAIN, batch_id]

            if status:
                query += " AND status = %s"
                params.append(status)

            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            await cur.execute(query, params)
            rows = await cur.fetchall()

            # Get total count
            count_query = """
                SELECT COUNT(*) FROM commandbus.command
                WHERE domain = %s AND batch_id = %s
            """
            count_params: list[Any] = [E2E_DOMAIN, batch_id]
            if status:
                count_query += " AND status = %s"
                count_params.append(status)
            await cur.execute(count_query, count_params)
            total_row = await cur.fetchone()
            total = total_row[0] if total_row else 0

        commands = [
            BatchCommandResponse(
                command_id=row[0],
                command_type=row[1],
                status=row[2],
                attempts=row[3],
                max_attempts=row[4],
                created_at=row[5],
                last_error_code=row[6],
                last_error_message=row[7],
            )
            for row in rows
        ]

        return BatchCommandsListResponse(
            commands=commands,
            total=total,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        return BatchCommandsListResponse(
            commands=[], total=0, limit=limit, offset=offset, error=str(e)
        )


# =============================================================================
# Reply Queue Endpoints
# =============================================================================

REPLY_QUEUE = "e2e__replies"


@api_router.get("/replies", response_model=ReplyQueueResponse)
async def list_replies(pool: Pool, limit: int = 20) -> ReplyQueueResponse:
    """List messages in the reply queue.

    Uses a short visibility timeout to peek at messages without consuming them.
    """
    from commandbus.pgmq.client import PgmqClient

    limit = min(limit, 100)
    pgmq = PgmqClient(pool)

    try:
        # Read messages with very short visibility timeout (1 second)
        # This allows peeking without permanently consuming
        messages = await pgmq.read(REPLY_QUEUE, visibility_timeout=1, batch_size=limit)

        # Get queue depth
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(f"SELECT COUNT(*) FROM pgmq.q_{REPLY_QUEUE}")
            row = await cur.fetchone()
            queue_depth = row[0] if row else 0

        reply_messages = []
        for msg in messages:
            reply_messages.append(
                ReplyMessage(
                    msg_id=msg.msg_id,
                    command_id=msg.message.get("command_id", ""),
                    correlation_id=msg.message.get("correlation_id"),
                    outcome=msg.message.get("outcome", "UNKNOWN"),
                    result=msg.message.get("result"),
                    enqueued_at=msg.enqueued_at,
                )
            )

        return ReplyQueueResponse(
            messages=reply_messages,
            queue_name=REPLY_QUEUE,
            queue_depth=queue_depth,
        )
    except Exception as e:
        return ReplyQueueResponse(
            messages=[],
            queue_name=REPLY_QUEUE,
            queue_depth=0,
            error=str(e),
        )


@api_router.delete("/replies/{msg_id}")
async def delete_reply(msg_id: int, pool: Pool) -> dict[str, Any]:
    """Delete a specific reply message from the queue."""
    from commandbus.pgmq.client import PgmqClient

    pgmq = PgmqClient(pool)
    try:
        await pgmq.delete(REPLY_QUEUE, msg_id)
        return {"status": "ok", "msg_id": msg_id, "message": "Reply deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@api_router.post("/replies/process")
async def process_replies(pool: Pool, limit: int = 100) -> dict[str, Any]:
    """Process replies from queue and update batch summaries.

    Reads replies, updates the corresponding batch_summary counts,
    and deletes processed messages.
    """
    from commandbus.pgmq.client import PgmqClient

    pgmq = PgmqClient(pool)
    processed = 0
    success_count = 0
    failed_count = 0
    canceled_count = 0

    try:
        # Read messages with longer visibility timeout for processing
        messages = await pgmq.read(REPLY_QUEUE, visibility_timeout=30, batch_size=limit)

        for msg in messages:
            # Get batch_id from correlation_id (batches set correlation_id = batch_id)
            correlation_id = msg.message.get("correlation_id")
            outcome = msg.message.get("outcome", "UNKNOWN")

            if correlation_id:
                # Update the appropriate counter based on outcome
                column = None
                if outcome == "SUCCESS":
                    column = "success_count"
                    success_count += 1
                elif outcome == "FAILED":
                    column = "failed_count"
                    failed_count += 1
                elif outcome == "CANCELED":
                    column = "canceled_count"
                    canceled_count += 1

                if column:
                    async with pool.connection() as conn, conn.cursor() as cur:
                        # Update count and check if complete
                        await cur.execute(
                            f"""
                            UPDATE e2e.batch_summary
                            SET {column} = {column} + 1,
                                completed_at = CASE
                                    WHEN success_count + failed_count + canceled_count + 1
                                         >= total_expected
                                    THEN NOW()
                                    ELSE completed_at
                                END
                            WHERE batch_id = %s
                            """,
                            (correlation_id,),
                        )

            # Delete processed message
            await pgmq.delete(REPLY_QUEUE, msg.msg_id)
            processed += 1

        return {
            "status": "ok",
            "processed": processed,
            "success": success_count,
            "failed": failed_count,
            "canceled": canceled_count,
            "message": f"Processed {processed} replies",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@api_router.delete("/replies")
async def clear_reply_queue(pool: Pool) -> dict[str, Any]:
    """Clear all messages from the reply queue."""
    try:
        async with pool.connection() as conn:
            await conn.execute(f"DELETE FROM pgmq.q_{REPLY_QUEUE}")
        return {"status": "ok", "message": "Reply queue cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@api_router.get("/reply-summaries", response_model=ReplySummaryListResponse)
async def list_reply_summaries(
    pool: Pool, limit: int = 20, offset: int = 0
) -> ReplySummaryListResponse:
    """List batch reply summaries."""
    limit = min(limit, 100)

    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, batch_id, domain, total_expected,
                       success_count, failed_count, canceled_count,
                       created_at, completed_at
                FROM e2e.batch_summary
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = await cur.fetchall()

            # Get total count
            await cur.execute("SELECT COUNT(*) FROM e2e.batch_summary")
            total_row = await cur.fetchone()
            total = total_row[0] if total_row else 0

        summaries = []
        for row in rows:
            success = row[4] or 0
            failed = row[5] or 0
            canceled = row[6] or 0
            total_received = success + failed + canceled
            total_expected = row[3] or 0

            summaries.append(
                ReplySummaryResponse(
                    id=row[0],
                    batch_id=row[1],
                    domain=row[2],
                    total_expected=total_expected,
                    success_count=success,
                    failed_count=failed,
                    canceled_count=canceled,
                    total_received=total_received,
                    is_complete=total_received >= total_expected,
                    created_at=row[7],
                    completed_at=row[8],
                )
            )

        return ReplySummaryListResponse(
            summaries=summaries,
            total=total,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        return ReplySummaryListResponse(
            summaries=[],
            total=0,
            limit=limit,
            offset=offset,
            error=str(e),
        )


@api_router.get("/reply-summaries/{batch_id}", response_model=ReplySummaryResponse)
async def get_reply_summary(batch_id: UUID, pool: Pool) -> ReplySummaryResponse:
    """Get a specific batch reply summary."""
    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, batch_id, domain, total_expected,
                       success_count, failed_count, canceled_count,
                       created_at, completed_at
                FROM e2e.batch_summary
                WHERE batch_id = %s
                """,
                (batch_id,),
            )
            row = await cur.fetchone()

            if not row:
                raise HTTPException(status_code=404, detail="Batch summary not found")

            success = row[4] or 0
            failed = row[5] or 0
            canceled = row[6] or 0
            total_received = success + failed + canceled
            total_expected = row[3] or 0

            return ReplySummaryResponse(
                id=row[0],
                batch_id=row[1],
                domain=row[2],
                total_expected=total_expected,
                success_count=success,
                failed_count=failed,
                canceled_count=canceled,
                total_received=total_received,
                is_complete=total_received >= total_expected,
                created_at=row[7],
                completed_at=row[8],
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
