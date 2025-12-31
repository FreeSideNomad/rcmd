"""E2E API routes - JSON endpoints."""

import random
import uuid
from datetime import UTC, datetime, timedelta

from flask import Blueprint, current_app, jsonify, request

api_bp = Blueprint("api", __name__)


def get_pool():
    """Get database pool from app context."""
    return current_app.config.get("pool")


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
    max_attempts = data.get("max_attempts")

    if max_attempts is not None:
        behavior["max_attempts"] = max_attempts

    command_id = uuid.uuid4()

    return jsonify(
        {
            "command_id": str(command_id),
            "status": "PENDING",
            "behavior": behavior,
            "payload": payload,
            "message": "Command created (database persistence coming in future iteration)",
        }
    ), 201


@api_bp.route("/commands/bulk", methods=["POST"])
def create_bulk_commands():
    """Create multiple test commands.

    Request body:
    {
        "count": 100,
        "behavior": {
            "type": "success",
            "execution_time_ms": 50
        }
    }
    """
    data = request.get_json() or {}

    count = min(data.get("count", 1), 1000)  # Cap at 1000
    behavior = data.get("behavior", {"type": "success"})

    command_ids = [str(uuid.uuid4()) for _ in range(count)]

    return jsonify(
        {
            "created": count,
            "command_ids": command_ids,
            "behavior": behavior,
            "message": "Commands created (database persistence coming in future iteration)",
        }
    ), 201


@api_bp.route("/commands", methods=["GET"])
def list_commands():
    """Query commands with filters.

    Query Parameters:
    - status: Filter by status (PENDING, IN_PROGRESS, COMPLETED, etc.)
    - domain: Filter by domain
    - command_type: Filter by command type
    - created_after: ISO datetime
    - created_before: ISO datetime
    - limit: Page size (default 20)
    - offset: Pagination offset
    """
    status = request.args.get("status")
    domain = request.args.get("domain")
    command_type = request.args.get("command_type")
    # Date filters captured for future DB implementation
    _ = request.args.get("created_after")
    _ = request.args.get("created_before")
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    # Generate mock data for demo purposes
    # In production this would call command_repository.query_commands()
    mock_commands = _generate_mock_commands(
        status=status,
        domain=domain,
        command_type=command_type,
        limit=limit,
        offset=offset,
    )

    return jsonify(
        {
            "commands": mock_commands,
            "total": 100,  # Mock total
            "limit": limit,
            "offset": offset,
        }
    )


@api_bp.route("/commands/<command_id>", methods=["GET"])
def get_command(command_id: str):
    """Get single command details."""
    return jsonify(
        {
            "command_id": command_id,
            "domain": "e2e",
            "command_type": "TestCommand",
            "status": "PENDING",
            "attempts": 0,
            "max_attempts": 3,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "correlation_id": str(uuid.uuid4()),
            "last_error_code": None,
            "last_error_message": None,
            "payload": {"behavior": {"type": "success"}},
        }
    )


def _generate_mock_commands(
    status: str | None = None,
    domain: str | None = None,
    command_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Generate mock commands for demo purposes."""
    statuses = ["PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED", "IN_TSQ"]
    if status:
        statuses = [status]

    commands = []
    base_time = datetime.now(UTC)

    for i in range(limit):
        cmd_status = random.choice(statuses)
        attempts = 0 if cmd_status == "PENDING" else random.randint(1, 3)
        created = base_time - timedelta(minutes=offset + i * 5)

        cmd = {
            "command_id": str(uuid.uuid4()),
            "domain": domain or "e2e",
            "command_type": command_type or "TestCommand",
            "status": cmd_status,
            "attempts": attempts,
            "max_attempts": 3,
            "created_at": created.isoformat(),
            "updated_at": created.isoformat(),
            "correlation_id": str(uuid.uuid4()),
            "last_error_code": "TRANSIENT_ERROR" if cmd_status == "IN_TSQ" else None,
            "last_error_message": "Temporary failure" if cmd_status == "IN_TSQ" else None,
        }
        commands.append(cmd)

    return commands


@api_bp.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@api_bp.route("/config", methods=["GET"])
def get_config():
    """Get current configuration."""
    # Return default config for now - will be loaded from DB in future
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
        }
    )


@api_bp.route("/config", methods=["PUT"])
def update_config():
    """Update configuration."""
    data = request.get_json()
    # Will be implemented with DB persistence in future
    return jsonify({"status": "ok", "config": data})


@api_bp.route("/stats/overview", methods=["GET"])
def stats_overview():
    """Get dashboard statistics."""
    # Placeholder - will be implemented with real data
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
            },
        }
    )


# =============================================================================
# Troubleshooting Queue (TSQ) Endpoints
# =============================================================================


@api_bp.route("/tsq", methods=["GET"])
def list_tsq_commands():
    """List commands in troubleshooting queue.

    Query Parameters:
    - domain: Filter by domain
    - limit: Page size (default 20)
    - offset: Pagination offset
    """
    domain = request.args.get("domain")
    limit = min(int(request.args.get("limit", 20)), 100)
    offset = int(request.args.get("offset", 0))

    # Generate mock TSQ data
    commands = _generate_mock_tsq_commands(domain=domain, limit=limit, offset=offset)

    return jsonify(
        {
            "commands": commands,
            "total": 15,  # Mock total
            "limit": limit,
            "offset": offset,
        }
    )


@api_bp.route("/tsq/<command_id>/retry", methods=["POST"])
def retry_tsq_command(command_id: str):
    """Retry a command from TSQ."""
    return jsonify(
        {
            "command_id": command_id,
            "status": "PENDING",
            "message": "Command re-queued for processing",
        }
    )


@api_bp.route("/tsq/<command_id>/cancel", methods=["POST"])
def cancel_tsq_command(command_id: str):
    """Cancel a command in TSQ."""
    return jsonify(
        {
            "command_id": command_id,
            "status": "CANCELLED",
            "message": "Command cancelled",
        }
    )


@api_bp.route("/tsq/<command_id>/complete", methods=["POST"])
def complete_tsq_command(command_id: str):
    """Manually complete a command in TSQ."""
    data = request.get_json() or {}
    result_data = data.get("result_data")
    operator = data.get("operator", "unknown")

    return jsonify(
        {
            "command_id": command_id,
            "status": "COMPLETED",
            "result_data": result_data,
            "operator": operator,
            "message": "Command manually completed",
        }
    )


@api_bp.route("/tsq/bulk-retry", methods=["POST"])
def bulk_retry_tsq_commands():
    """Retry multiple commands from TSQ."""
    data = request.get_json() or {}
    command_ids = data.get("command_ids", [])

    return jsonify(
        {
            "retried": len(command_ids),
            "command_ids": command_ids,
            "message": f"{len(command_ids)} commands re-queued for processing",
        }
    )


def _generate_mock_tsq_commands(
    domain: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Generate mock TSQ commands for demo purposes."""
    error_codes = ["INVALID_DATA", "ACCOUNT_NOT_FOUND", "TIMEOUT", "RATE_LIMITED"]
    error_types = ["PERMANENT", "TRANSIENT"]

    commands = []
    base_time = datetime.now(UTC)

    for i in range(min(limit, 15 - offset)):  # TSQ usually has fewer items
        error_code = random.choice(error_codes)
        error_type = random.choice(error_types)
        created = base_time - timedelta(hours=offset + i * 2)

        cmd = {
            "command_id": str(uuid.uuid4()),
            "domain": domain or "e2e",
            "command_type": "TestCommand",
            "status": "IN_TSQ",
            "attempts": 3,
            "max_attempts": 3,
            "last_error_type": error_type,
            "last_error_code": error_code,
            "last_error_message": f"Error: {error_code.replace('_', ' ').lower()}",
            "created_at": created.isoformat(),
            "updated_at": (created + timedelta(minutes=30)).isoformat(),
            "first_failure_at": created.isoformat(),
            "last_failure_at": (created + timedelta(minutes=30)).isoformat(),
            "behavior": {
                "type": "fail_permanent",
                "error_code": error_code,
            },
        }
        commands.append(cmd)

    return commands


# =============================================================================
# Audit Trail Endpoints
# =============================================================================


@api_bp.route("/audit/<command_id>", methods=["GET"])
def get_audit_trail(command_id: str):
    """Get audit trail for a specific command.

    Returns chronological list of events for the command.
    """
    event_type = request.args.get("event_type")

    # Generate mock audit events for demo
    events = _generate_mock_audit_events(command_id, event_type)

    # Calculate total duration
    if events:
        first_ts = datetime.fromisoformat(events[0]["timestamp"].replace("Z", "+00:00"))
        last_ts = datetime.fromisoformat(events[-1]["timestamp"].replace("Z", "+00:00"))
        total_duration_ms = int((last_ts - first_ts).total_seconds() * 1000)
    else:
        total_duration_ms = 0

    return jsonify(
        {
            "command_id": command_id,
            "events": events,
            "total_duration_ms": total_duration_ms,
        }
    )


@api_bp.route("/audit/search", methods=["GET"])
def search_audit_events():
    """Search audit events across commands.

    Query Parameters:
    - event_type: Filter by event type
    - domain: Filter by domain
    - start_date: ISO datetime
    - end_date: ISO datetime
    - limit: Page size (default 50)
    - offset: Pagination offset
    """
    event_type = request.args.get("event_type")
    domain = request.args.get("domain")
    # Date filters captured for future DB implementation
    _ = request.args.get("start_date")
    _ = request.args.get("end_date")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    # Generate mock events for demo
    events = _generate_mock_search_events(
        event_type=event_type, domain=domain, limit=limit, offset=offset
    )

    return jsonify(
        {
            "events": events,
            "total": 150,  # Mock total
            "limit": limit,
            "offset": offset,
        }
    )


def _generate_mock_audit_events(
    command_id: str,
    event_type_filter: str | None = None,
) -> list[dict]:
    """Generate mock audit events for a command."""
    # Create a realistic command lifecycle
    base_time = datetime.now(UTC) - timedelta(hours=1)

    all_events = [
        {
            "id": 1,
            "event_type": "SENT",
            "timestamp": base_time.isoformat().replace("+00:00", "Z"),
            "details": {
                "msg_id": random.randint(10000, 99999),
                "domain": "e2e",
                "command_type": "TestCommand",
                "correlation_id": str(uuid.uuid4()),
            },
        },
        {
            "id": 2,
            "event_type": "STARTED",
            "timestamp": (base_time + timedelta(milliseconds=50))
            .isoformat()
            .replace("+00:00", "Z"),
            "details": {
                "worker_id": "worker-1",
                "attempt": 1,
            },
        },
        {
            "id": 3,
            "event_type": "FAILED",
            "timestamp": (base_time + timedelta(milliseconds=300))
            .isoformat()
            .replace("+00:00", "Z"),
            "details": {
                "error_type": "TRANSIENT",
                "error_code": "CONNECTION_TIMEOUT",
                "error_message": "Connection timeout after 200ms",
                "attempt": 1,
                "max_attempts": 3,
            },
        },
        {
            "id": 4,
            "event_type": "STARTED",
            "timestamp": (base_time + timedelta(milliseconds=1300))
            .isoformat()
            .replace("+00:00", "Z"),
            "details": {
                "worker_id": "worker-1",
                "attempt": 2,
            },
        },
        {
            "id": 5,
            "event_type": "COMPLETED",
            "timestamp": (base_time + timedelta(milliseconds=1400))
            .isoformat()
            .replace("+00:00", "Z"),
            "details": {
                "attempt": 2,
                "result": {"status": "success", "data": {"processed": True}},
            },
        },
    ]

    # Filter by event type if specified
    if event_type_filter:
        all_events = [e for e in all_events if e["event_type"] == event_type_filter]

    return all_events


def _generate_mock_search_events(
    event_type: str | None = None,
    domain: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Generate mock search events for demo purposes."""
    event_types = ["SENT", "STARTED", "COMPLETED", "FAILED", "MOVED_TO_TSQ"]
    if event_type:
        event_types = [event_type]

    events = []
    base_time = datetime.now(UTC)

    for i in range(limit):
        evt_type = random.choice(event_types)
        created = base_time - timedelta(minutes=offset + i * 2)

        evt = {
            "id": offset + i + 1,
            "command_id": str(uuid.uuid4()),
            "event_type": evt_type,
            "timestamp": created.isoformat().replace("+00:00", "Z"),
            "domain": domain or "e2e",
            "command_type": "TestCommand",
            "details": _get_event_details(evt_type),
        }
        events.append(evt)

    return events


def _get_event_details(event_type: str) -> dict:
    """Get mock details for an event type."""
    details_map = {
        "SENT": {"msg_id": random.randint(10000, 99999), "correlation_id": str(uuid.uuid4())},
        "STARTED": {"worker_id": f"worker-{random.randint(1, 4)}", "attempt": 1},
        "COMPLETED": {"attempt": random.randint(1, 3), "result": {"status": "success"}},
        "FAILED": {
            "error_type": random.choice(["TRANSIENT", "PERMANENT"]),
            "error_code": random.choice(["TIMEOUT", "INVALID_DATA", "CONNECTION_ERROR"]),
            "attempt": random.randint(1, 3),
        },
        "MOVED_TO_TSQ": {
            "reason": "max_attempts_exceeded",
            "attempts": 3,
            "last_error": "CONNECTION_ERROR",
        },
    }
    return details_map.get(event_type, {})
