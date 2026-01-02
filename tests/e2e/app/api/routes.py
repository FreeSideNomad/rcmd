"""E2E API routes - JSON endpoints with real database connectivity."""

from __future__ import annotations

import random
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from flask import Blueprint, current_app, jsonify, request

from commandbus.bus import CommandBus
from commandbus.ops.troubleshooting import TroubleshootingQueue

from .. import run_async

if TYPE_CHECKING:
    from psycopg_pool import AsyncConnectionPool

api_bp = Blueprint("api", __name__)

# Domain used for E2E demo commands
E2E_DOMAIN = "e2e"


async def get_pool() -> AsyncConnectionPool:
    """Get and open database pool from app context."""
    pool = current_app.config.get("pool")
    if pool is None:
        raise RuntimeError("Database pool not initialized")

    if not current_app.config.get("pool_opened"):
        await pool.open()
        current_app.config["pool_opened"] = True

    return pool


# =============================================================================
# Command Endpoints
# =============================================================================


@api_bp.route("/commands", methods=["POST"])
def create_command():
    """Create a single test command.

    Request body:
    {
        "behavior": {
            "type": "success|fail_permanent|fail_transient|fail_transient_then_succeed|timeout",
            "transient_failures": 2,  # for fail_transient_then_succeed
            "error_code": "INVALID_ACCOUNT",  # for failure types
            "error_message": "Account not found",  # for failure types
            "execution_time_ms": 100  # optional delay
        },
        "payload": {"custom": "data"},  # optional
        "max_attempts": 5  # optional override
    }
    """
    data = request.get_json() or {}

    behavior = data.get("behavior", {"type": "success"})
    payload = data.get("payload", {})
    max_attempts = data.get("max_attempts", 3)

    command_id = uuid4()

    async def _create():
        pool = await get_pool()
        bus = CommandBus(pool)
        await bus.send(
            domain=E2E_DOMAIN,
            command_type="TestCommand",
            command_id=command_id,
            data={"behavior": behavior, "payload": payload},
            max_attempts=max_attempts,
        )
        return command_id

    try:
        run_async(_create())
        return jsonify(
            {
                "command_id": str(command_id),
                "status": "PENDING",
                "behavior": behavior,
                "payload": payload,
                "message": "Command created and queued",
            }
        ), 201
    except Exception as e:
        return jsonify({"error": str(e), "message": "Failed to create command"}), 500


@api_bp.route("/commands/bulk", methods=["POST"])
def create_bulk_commands():
    """Create multiple test commands for load testing.

    Request body:
    {
        "count": 100,
        "behavior_distribution": {
            "success": 90,
            "fail_transient_then_succeed": 5,
            "fail_permanent": 5
        },
        "execution_time_ms": 10
    }
    """
    start_time = time.time()
    data = request.get_json() or {}

    count = min(data.get("count", 1), 10000)
    execution_time_ms = data.get("execution_time_ms", 0)
    behavior_distribution = data.get("behavior_distribution")
    simple_behavior = data.get("behavior")
    max_attempts = data.get("max_attempts", 3)

    command_ids: list[UUID] = []
    behaviors_assigned: dict[str, int] = {}

    async def _create_bulk():
        pool = await get_pool()
        bus = CommandBus(pool)

        for _ in range(count):
            cmd_id = uuid4()
            command_ids.append(cmd_id)

            if behavior_distribution:
                behavior = _select_behavior_from_distribution(
                    behavior_distribution, execution_time_ms
                )
                btype = behavior["type"]
                behaviors_assigned[btype] = behaviors_assigned.get(btype, 0) + 1
            elif simple_behavior:
                behavior = simple_behavior
            else:
                behavior = {"type": "success", "execution_time_ms": execution_time_ms}

            await bus.send(
                domain=E2E_DOMAIN,
                command_type="TestCommand",
                command_id=cmd_id,
                data={"behavior": behavior},
                max_attempts=max_attempts,
            )

    try:
        generation_start = time.time()
        run_async(_create_bulk())
        generation_time_ms = int((time.time() - generation_start) * 1000)

        return jsonify(
            {
                "created": count,
                "command_ids": [str(cid) for cid in command_ids[:100]],
                "total_command_ids": count,
                "generation_time_ms": generation_time_ms,
                "queue_time_ms": int((time.time() - start_time) * 1000),
                "behavior_distribution": behaviors_assigned if behavior_distribution else None,
                "message": f"{count} commands created and queued",
            }
        ), 201
    except Exception as e:
        return jsonify({"error": str(e), "message": "Failed to create bulk commands"}), 500


def _select_behavior_from_distribution(distribution: dict, execution_time_ms: int = 0) -> dict:
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


@api_bp.route("/commands", methods=["GET"])
def list_commands():
    """Query commands with filters."""
    status = request.args.get("status")
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    async def _list():
        pool = await get_pool()
        async with pool.connection() as conn:
            # Build query with optional status filter
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

            commands = []
            for row in rows:
                commands.append(
                    {
                        "command_id": str(row[0]),
                        "domain": row[1],
                        "command_type": row[2],
                        "status": row[3],
                        "attempts": row[4],
                        "max_attempts": row[5],
                        "created_at": row[6].isoformat() if row[6] else None,
                        "updated_at": row[7].isoformat() if row[7] else None,
                        "last_error_code": row[8],
                        "last_error_message": row[9],
                        "correlation_id": str(row[10]) if row[10] else None,
                    }
                )

            return commands, total

    try:
        commands, total = run_async(_list())
        return jsonify(
            {
                "commands": commands,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )
    except Exception as e:
        return jsonify({"error": str(e), "commands": [], "total": 0}), 500


@api_bp.route("/commands/<command_id>", methods=["GET"])
def get_command(command_id: str):
    """Get single command details."""

    async def _get():
        pool = await get_pool()
        bus = CommandBus(pool)
        return await bus.get_command(E2E_DOMAIN, UUID(command_id))

    try:
        cmd = run_async(_get())
        if cmd is None:
            return jsonify({"error": "Command not found"}), 404

        return jsonify(
            {
                "command_id": str(cmd.command_id),
                "domain": cmd.domain,
                "command_type": cmd.command_type,
                "status": cmd.status.value,
                "attempts": cmd.attempts,
                "max_attempts": cmd.max_attempts,
                "created_at": cmd.created_at.isoformat() if cmd.created_at else None,
                "updated_at": cmd.updated_at.isoformat() if cmd.updated_at else None,
                "correlation_id": str(cmd.correlation_id) if cmd.correlation_id else None,
                "last_error_code": cmd.last_error_code,
                "last_error_message": cmd.last_error_msg,
                "payload": cmd.data,
            }
        )
    except ValueError:
        return jsonify({"error": "Invalid command ID format"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Stats Endpoints
# =============================================================================


@api_bp.route("/stats/overview", methods=["GET"])
def stats_overview():
    """Get dashboard statistics from real database."""

    async def _stats():
        pool = await get_pool()
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
                # Map IN_TROUBLESHOOTING_QUEUE to IN_TSQ for UI
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

            return {
                "status_counts": status_counts,
                "processing_rate": {
                    "per_minute": per_minute,
                    "avg_time_ms": avg_time_ms,
                    "p50_ms": p50_ms,
                    "p95_ms": p95_ms,
                    "p99_ms": p99_ms,
                },
                "recent_change": {
                    "PENDING": 0,
                    "COMPLETED": per_minute,
                },
            }

    try:
        stats = run_async(_stats())
        return jsonify(stats)
    except Exception as e:
        # Return zeros on error rather than failing completely
        return jsonify(
            {
                "status_counts": {
                    "PENDING": 0,
                    "IN_PROGRESS": 0,
                    "COMPLETED": 0,
                    "CANCELLED": 0,
                    "IN_TSQ": 0,
                },
                "processing_rate": {
                    "per_minute": 0,
                    "avg_time_ms": 0,
                    "p50_ms": 0,
                    "p95_ms": 0,
                    "p99_ms": 0,
                },
                "recent_change": {"PENDING": 0, "COMPLETED": 0},
                "error": str(e),
            }
        )


@api_bp.route("/stats/recent-activity", methods=["GET"])
def recent_activity():
    """Get recent activity feed from audit table."""
    limit = min(int(request.args.get("limit", 10)), 50)

    async def _activity():
        pool = await get_pool()
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
                    {
                        "command_id": str(row[0]),
                        "event_type": event_type,
                        "timestamp": row[2].isoformat() if row[2] else None,
                        "summary": summary_map.get(event_type, f"{cmd_type} {event_type.lower()}"),
                    }
                )

            return events

    try:
        events = run_async(_activity())
        return jsonify({"events": events})
    except Exception as e:
        return jsonify({"events": [], "error": str(e)})


@api_bp.route("/stats/throughput", methods=["GET"])
def stats_throughput():
    """Get processing throughput metrics."""
    window_seconds = int(request.args.get("window", 60))

    async def _throughput():
        pool = await get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            # Get commands completed in window
            await cur.execute(
                """
                    SELECT COUNT(*) FROM command_bus_audit
                    WHERE domain = %s
                      AND event_type = 'COMPLETED'
                      AND ts > NOW() - INTERVAL '%s seconds'
                """,
                (E2E_DOMAIN, window_seconds),
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

            return {
                "window_seconds": window_seconds,
                "commands_processed": commands_processed,
                "throughput_per_second": round(commands_processed / window_seconds, 1)
                if window_seconds > 0
                else 0,
                "avg_processing_time_ms": 0,
                "p50_ms": 0,
                "p95_ms": 0,
                "p99_ms": 0,
                "active_workers": 0,
                "queue_depth": queue_depth,
            }

    try:
        result = run_async(_throughput())
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "window_seconds": window_seconds, "commands_processed": 0})


@api_bp.route("/stats/load-test", methods=["GET"])
def stats_load_test():
    """Get load test progress."""
    total_commands = int(request.args.get("total", 10000))

    async def _load_test():
        pool = await get_pool()
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

            counts = {}
            for row in rows:
                counts[row[0]] = row[1]

            completed = counts.get("COMPLETED", 0)
            failed = counts.get("CANCELLED", 0)
            in_tsq = counts.get("IN_TROUBLESHOOTING_QUEUE", 0)
            pending = counts.get("PENDING", 0) + counts.get("IN_PROGRESS", 0)
            total = completed + failed + in_tsq + pending

            return {
                "total_commands": total if total > 0 else total_commands,
                "completed": completed,
                "failed": failed,
                "in_tsq": in_tsq,
                "pending": pending,
                "progress_percent": round((completed / total) * 100, 1) if total > 0 else 0,
                "elapsed_seconds": 0,
                "estimated_remaining_seconds": 0,
                "throughput_per_second": 0,
            }

    try:
        result = run_async(_load_test())
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "total_commands": 0, "completed": 0})


# =============================================================================
# Health & Config Endpoints
# =============================================================================


@api_bp.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""

    async def _check():
        pool = await get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT 1")
            return True

    try:
        run_async(_check())
        return jsonify({"status": "ok", "database": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "database": "disconnected", "error": str(e)}), 503


@api_bp.route("/config", methods=["GET"])
def get_config():
    """Get current configuration from database."""

    async def _get_config():
        pool = await get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT key, value FROM e2e_config")
            rows = await cur.fetchall()
            config = {}
            for row in rows:
                config[row[0]] = row[1]
            return config

    try:
        config = run_async(_get_config())
        return jsonify(
            {
                "worker": config.get(
                    "worker",
                    {
                        "visibility_timeout": 30,
                        "concurrency": 4,
                        "poll_interval": 1.0,
                        "batch_size": 10,
                    },
                ),
                "retry": config.get(
                    "retry",
                    {
                        "max_attempts": 3,
                        "base_delay_ms": 1000,
                        "max_delay_ms": 60000,
                        "backoff_multiplier": 2.0,
                    },
                ),
            }
        )
    except Exception as e:
        # Return defaults on error
        return jsonify(
            {
                "worker": {
                    "visibility_timeout": 30,
                    "concurrency": 4,
                    "poll_interval": 1.0,
                    "batch_size": 10,
                },
                "retry": {
                    "max_attempts": 3,
                    "base_delay_ms": 1000,
                    "max_delay_ms": 60000,
                    "backoff_multiplier": 2.0,
                },
                "error": str(e),
            }
        )


@api_bp.route("/config", methods=["PUT"])
def update_config():
    """Update configuration in database."""
    data = request.get_json() or {}

    async def _update_config():
        pool = await get_pool()
        async with pool.connection() as conn, conn.cursor() as cur:
            if "worker" in data:
                await cur.execute(
                    """
                        INSERT INTO e2e_config (key, value, updated_at)
                        VALUES ('worker', %s, NOW())
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                    (data["worker"],),
                )
            if "retry" in data:
                await cur.execute(
                    """
                        INSERT INTO e2e_config (key, value, updated_at)
                        VALUES ('retry', %s, NOW())
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                    """,
                    (data["retry"],),
                )

    try:
        run_async(_update_config())
        return jsonify({"status": "ok", "config": data})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


# =============================================================================
# Troubleshooting Queue (TSQ) Endpoints
# =============================================================================


@api_bp.route("/tsq", methods=["GET"])
def list_tsq_commands():
    """List commands in troubleshooting queue."""
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    async def _list_tsq():
        pool = await get_pool()
        tsq = TroubleshootingQueue(pool)
        commands = await tsq.list_commands(E2E_DOMAIN, limit=limit, offset=offset)

        result = []
        for cmd in commands:
            result.append(
                {
                    "command_id": str(cmd.command_id),
                    "domain": cmd.domain,
                    "command_type": cmd.command_type,
                    "status": "IN_TSQ",
                    "attempts": cmd.attempts,
                    "max_attempts": cmd.max_attempts,
                    "last_error_type": cmd.last_error_type,
                    "last_error_code": cmd.last_error_code,
                    "last_error_message": cmd.last_error_msg,
                    "created_at": cmd.created_at.isoformat() if cmd.created_at else None,
                    "updated_at": cmd.updated_at.isoformat() if cmd.updated_at else None,
                }
            )

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

        return result, total

    try:
        commands, total = run_async(_list_tsq())
        return jsonify(
            {
                "commands": commands,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )
    except Exception as e:
        return jsonify({"commands": [], "total": 0, "error": str(e)})


@api_bp.route("/tsq/<command_id>/retry", methods=["POST"])
def retry_tsq_command(command_id: str):
    """Retry a command from TSQ."""
    data = request.get_json() or {}
    operator = data.get("operator", "e2e-ui")

    async def _retry():
        pool = await get_pool()
        tsq = TroubleshootingQueue(pool)
        await tsq.operator_retry(E2E_DOMAIN, UUID(command_id), operator=operator)

    try:
        run_async(_retry())
        return jsonify(
            {
                "command_id": command_id,
                "status": "PENDING",
                "message": "Command re-queued for processing",
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/tsq/<command_id>/cancel", methods=["POST"])
def cancel_tsq_command(command_id: str):
    """Cancel a command in TSQ."""
    data = request.get_json() or {}
    operator = data.get("operator", "e2e-ui")
    reason = data.get("reason", "Cancelled via UI")

    async def _cancel():
        pool = await get_pool()
        tsq = TroubleshootingQueue(pool)
        await tsq.operator_cancel(E2E_DOMAIN, UUID(command_id), operator=operator, reason=reason)

    try:
        run_async(_cancel())
        return jsonify(
            {
                "command_id": command_id,
                "status": "CANCELLED",
                "message": "Command cancelled",
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/tsq/<command_id>/complete", methods=["POST"])
def complete_tsq_command(command_id: str):
    """Manually complete a command in TSQ."""
    data = request.get_json() or {}
    result_data = data.get("result_data")
    operator = data.get("operator", "e2e-ui")

    async def _complete():
        pool = await get_pool()
        tsq = TroubleshootingQueue(pool)
        await tsq.operator_complete(
            E2E_DOMAIN,
            UUID(command_id),
            result_data=result_data,
            operator=operator,
        )

    try:
        run_async(_complete())
        return jsonify(
            {
                "command_id": command_id,
                "status": "COMPLETED",
                "result_data": result_data,
                "operator": operator,
                "message": "Command manually completed",
            }
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/tsq/bulk-retry", methods=["POST"])
def bulk_retry_tsq_commands():
    """Retry multiple commands from TSQ."""
    data = request.get_json() or {}
    command_ids = data.get("command_ids", [])
    operator = data.get("operator", "e2e-ui")

    async def _bulk_retry():
        pool = await get_pool()
        tsq = TroubleshootingQueue(pool)
        retried = 0
        for cmd_id in command_ids:
            try:
                await tsq.operator_retry(E2E_DOMAIN, UUID(cmd_id), operator=operator)
                retried += 1
            except Exception:
                pass  # Skip failed retries
        return retried

    try:
        retried = run_async(_bulk_retry())
        return jsonify(
            {
                "retried": retried,
                "command_ids": command_ids,
                "message": f"{retried} commands re-queued for processing",
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Audit Trail Endpoints
# =============================================================================


@api_bp.route("/audit/<command_id>", methods=["GET"])
def get_audit_trail(command_id: str):
    """Get audit trail for a specific command."""

    async def _get_audit():
        pool = await get_pool()
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

            events = []
            for row in rows:
                events.append(
                    {
                        "id": row[0],
                        "event_type": row[1],
                        "timestamp": row[2].isoformat() if row[2] else None,
                        "details": row[3] or {},
                    }
                )

            # Calculate duration
            total_duration_ms = 0
            if len(events) >= 2:
                first_ts = datetime.fromisoformat(events[0]["timestamp"].replace("Z", "+00:00"))
                last_ts = datetime.fromisoformat(events[-1]["timestamp"].replace("Z", "+00:00"))
                total_duration_ms = int((last_ts - first_ts).total_seconds() * 1000)

            return events, total_duration_ms

    try:
        events, duration = run_async(_get_audit())
        return jsonify(
            {
                "command_id": command_id,
                "events": events,
                "total_duration_ms": duration,
            }
        )
    except ValueError:
        return jsonify({"error": "Invalid command ID format"}), 400
    except Exception as e:
        return jsonify({"command_id": command_id, "events": [], "error": str(e)})


@api_bp.route("/audit/search", methods=["GET"])
def search_audit_events():
    """Search audit events across commands."""
    event_type = request.args.get("event_type")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    async def _search():
        pool = await get_pool()
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

            events = []
            for row in rows:
                events.append(
                    {
                        "id": row[0],
                        "command_id": str(row[1]),
                        "event_type": row[2],
                        "timestamp": row[3].isoformat() if row[3] else None,
                        "details": row[4] or {},
                        "domain": E2E_DOMAIN,
                        "command_type": row[5] or "TestCommand",
                    }
                )

            # Get total count
            count_query = "SELECT COUNT(*) FROM command_bus_audit WHERE domain = %s"
            count_params: list[Any] = [E2E_DOMAIN]
            if event_type:
                count_query += " AND event_type = %s"
                count_params.append(event_type)
            await cur.execute(count_query, count_params)
            total_row = await cur.fetchone()
            total = total_row[0] if total_row else 0

            return events, total

    try:
        events, total = run_async(_search())
        return jsonify(
            {
                "events": events,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )
    except Exception as e:
        return jsonify({"events": [], "total": 0, "error": str(e)})
