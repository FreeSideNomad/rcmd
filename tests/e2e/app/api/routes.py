"""E2E API routes - FastAPI endpoints with native async."""

from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from ..dependencies import TSQ, Bus, Pool
from .schemas import (
    ActivityEvent,
    AuditEvent,
    AuditSearchEvent,
    AuditSearchResponse,
    AuditTrailResponse,
    BulkCreateRequest,
    BulkCreateResponse,
    CommandListResponse,
    CommandResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    CreateCommandRequest,
    CreateCommandResponse,
    HealthResponse,
    LoadTestResponse,
    ProcessingRate,
    RecentActivityResponse,
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
async def create_command(request: CreateCommandRequest, bus: Bus) -> CreateCommandResponse:
    """Create a single test command."""
    command_id = uuid4()

    await bus.send(
        domain=E2E_DOMAIN,
        command_type="TestCommand",
        command_id=command_id,
        data={"behavior": request.behavior.model_dump(), "payload": request.payload},
        max_attempts=request.max_attempts,
    )

    return CreateCommandResponse(
        command_id=command_id,
        behavior=request.behavior,
        payload=request.payload,
        message="Command created and queued",
    )


@api_router.post("/commands/bulk", response_model=BulkCreateResponse, status_code=201)
async def create_bulk_commands(request: BulkCreateRequest, bus: Bus) -> BulkCreateResponse:
    """Create multiple test commands for load testing."""
    start_time = time.time()

    count = min(request.count, 10000)
    command_ids: list[UUID] = []
    behaviors_assigned: dict[str, int] = {}

    for _ in range(count):
        cmd_id = uuid4()
        command_ids.append(cmd_id)

        if request.behavior_distribution:
            behavior = _select_behavior_from_distribution(
                request.behavior_distribution, request.execution_time_ms
            )
            btype = behavior["type"]
            behaviors_assigned[btype] = behaviors_assigned.get(btype, 0) + 1
        elif request.behavior:
            behavior = request.behavior.model_dump()
        else:
            behavior = {"type": "success", "execution_time_ms": request.execution_time_ms}

        await bus.send(
            domain=E2E_DOMAIN,
            command_type="TestCommand",
            command_id=cmd_id,
            data={"behavior": behavior},
            max_attempts=request.max_attempts,
        )

    generation_time_ms = int((time.time() - start_time) * 1000)

    return BulkCreateResponse(
        created=count,
        command_ids=[str(cid) for cid in command_ids[:100]],
        total_command_ids=count,
        generation_time_ms=generation_time_ms,
        queue_time_ms=int((time.time() - start_time) * 1000),
        behavior_distribution=behaviors_assigned if request.behavior_distribution else None,
        message=f"{count} commands created and queued",
    )


def _select_behavior_from_distribution(
    distribution: dict[str, int], execution_time_ms: int
) -> dict[str, Any]:
    """Select a behavior based on weighted distribution."""
    total = sum(distribution.values())
    if total == 0:
        return {"type": "success", "execution_time_ms": execution_time_ms}

    rand = random.randint(1, total)
    cumulative = 0

    for behavior_type, weight in distribution.items():
        cumulative += weight
        if rand <= cumulative:
            behavior: dict[str, Any] = {
                "type": behavior_type,
                "execution_time_ms": execution_time_ms,
            }
            if behavior_type == "fail_transient_then_succeed":
                behavior["transient_failures"] = 2
            elif behavior_type in ("fail_permanent", "fail_transient"):
                behavior["error_code"] = "LOAD_TEST_ERROR"
                behavior["error_message"] = "Load test simulated failure"
            return behavior

    return {"type": "success", "execution_time_ms": execution_time_ms}


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
            FROM command_bus_command
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
            count_query = "SELECT COUNT(*) FROM command_bus_command WHERE domain = %s"
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
                FROM command_bus_command
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
                FROM command_bus_audit
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
                FROM command_bus_audit
                WHERE domain = %s
                  AND command_id IN (
                      SELECT DISTINCT command_id FROM command_bus_audit
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
                FROM command_bus_audit a
                LEFT JOIN command_bus_command c
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
                    SELECT COUNT(*) FROM command_bus_audit
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
                    SELECT COUNT(*) FROM command_bus_command
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
                    SELECT status, COUNT(*) FROM command_bus_command
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
            await cur.execute("SELECT key, value FROM e2e_config")
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
                        INSERT INTO e2e_config (key, value, updated_at)
                        VALUES ('worker', %s, NOW())
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                    (request.worker.model_dump(),),
                )
            if request.retry:
                await cur.execute(
                    """
                        INSERT INTO e2e_config (key, value, updated_at)
                        VALUES ('retry', %s, NOW())
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                    (request.retry.model_dump(),),
                )

        return ConfigUpdateResponse(status="ok", config=request)
    except Exception as e:
        return ConfigUpdateResponse(status="error", error=str(e))


# =============================================================================
# Troubleshooting Queue (TSQ) Endpoints
# =============================================================================


@api_router.get("/tsq", response_model=TSQListResponse)
async def list_tsq_commands(
    tsq: TSQ, pool: Pool, limit: int = 20, offset: int = 0
) -> TSQListResponse:
    """List commands in troubleshooting queue."""
    limit = min(limit, 100)

    try:
        commands = await tsq.list_commands(E2E_DOMAIN, limit=limit, offset=offset)

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

        # Get total count
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                    SELECT COUNT(*) FROM command_bus_command
                    WHERE domain = %s AND status = 'IN_TROUBLESHOOTING_QUEUE'
                """,
                (E2E_DOMAIN,),
            )
            row = await cur.fetchone()
            total = row[0] if row else 0

        return TSQListResponse(commands=result, total=total, limit=limit, offset=offset)
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
    for cmd_id in request.command_ids:
        try:
            await tsq.operator_retry(E2E_DOMAIN, UUID(cmd_id), operator=request.operator)
            retried += 1
        except Exception:
            pass  # Skip failed retries

    return TSQBulkRetryResponse(
        retried=retried,
        command_ids=request.command_ids,
        message=f"{retried} commands re-queued for processing",
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
                    FROM command_bus_audit
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
                FROM command_bus_audit a
                LEFT JOIN command_bus_command c
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
            count_query = "SELECT COUNT(*) FROM command_bus_audit WHERE domain = %s"
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
