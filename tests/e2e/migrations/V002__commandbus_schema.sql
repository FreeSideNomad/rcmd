-- Command Bus core tables

-- Commands table
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
    reply_queue       TEXT NOT NULL DEFAULT '',
    correlation_id    UUID NULL
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
