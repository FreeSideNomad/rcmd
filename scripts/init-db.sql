-- Initialize database for Command Bus
-- This script runs automatically when the PostgreSQL container starts

-- Enable PGMQ extension
CREATE EXTENSION IF NOT EXISTS pgmq;

-- Create command bus tables
CREATE TABLE IF NOT EXISTS command_bus_command (
    domain            TEXT NOT NULL,
    queue_name        TEXT NOT NULL,
    msg_id            BIGINT NULL,
    command_id        UUID NOT NULL,
    command_type      TEXT NOT NULL,
    status            TEXT NOT NULL,
    attempts          INT NOT NULL DEFAULT 0,
    max_attempts      INT NOT NULL,
    lease_expires_at  TIMESTAMPTZ NULL,
    last_error_type   TEXT NULL,
    last_error_code   TEXT NULL,
    last_error_msg    TEXT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reply_queue       TEXT NOT NULL,
    correlation_id    UUID NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_command_bus_command_domain_cmdid
    ON command_bus_command(domain, command_id);

CREATE INDEX IF NOT EXISTS ix_command_bus_command_status_type
    ON command_bus_command(status, command_type);

CREATE INDEX IF NOT EXISTS ix_command_bus_command_updated
    ON command_bus_command(updated_at);

-- Audit table (append-only)
CREATE TABLE IF NOT EXISTS command_bus_audit (
    audit_id      BIGSERIAL PRIMARY KEY,
    domain        TEXT NOT NULL,
    command_id    UUID NOT NULL,
    event_type    TEXT NOT NULL,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details_json  JSONB NULL
);

CREATE INDEX IF NOT EXISTS ix_command_bus_audit_cmdid_ts
    ON command_bus_audit(command_id, ts);

-- Optional payload archive
CREATE TABLE IF NOT EXISTS command_bus_payload_archive (
    domain        TEXT NOT NULL,
    command_id    UUID NOT NULL,
    payload_json  JSONB NOT NULL,
    archived_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(domain, command_id)
);

-- Create sample queues for testing
SELECT pgmq.create('test__commands');
SELECT pgmq.create('test__replies');
SELECT pgmq.create('payments__commands');
SELECT pgmq.create('payments__replies');

-- Grant permissions (for non-superuser access if needed)
-- GRANT ALL ON ALL TABLES IN SCHEMA public TO your_app_user;
-- GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO your_app_user;
