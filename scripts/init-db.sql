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
    reply_queue       TEXT NOT NULL DEFAULT '',
    correlation_id    UUID NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_command_bus_command_domain_cmdid
    ON command_bus_command(domain, command_id);

CREATE INDEX IF NOT EXISTS ix_command_bus_command_status_type
    ON command_bus_command(status, command_type);

CREATE INDEX IF NOT EXISTS ix_command_bus_command_status_created
    ON command_bus_command(status, created_at DESC);

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
SELECT pgmq.create('reports__commands');
SELECT pgmq.create('reports__replies');

-- Create E2E demo application queues
SELECT pgmq.create('e2e__commands');
SELECT pgmq.create('e2e__replies');

-- E2E demo application configuration table
CREATE TABLE IF NOT EXISTS e2e_config (
    key           TEXT PRIMARY KEY,
    value         JSONB NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Insert default E2E configuration
INSERT INTO e2e_config (key, value) VALUES
    ('worker', '{"visibility_timeout": 30, "concurrency": 4, "poll_interval": 1.0, "batch_size": 10}'::jsonb),
    ('retry', '{"max_attempts": 3, "backoff_schedule": [10, 60, 300]}'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- ============================================================================
-- Stored Procedures for Command Bus
-- These combine command + audit operations into single DB calls for performance
-- ============================================================================

-- sp_receive_command: Atomically receive a command
-- Combines: get metadata + increment attempts + update status + insert audit
-- Returns NULL if command not found or in terminal state
CREATE OR REPLACE FUNCTION sp_receive_command(
    p_domain TEXT,
    p_command_id UUID,
    p_new_status TEXT DEFAULT 'IN_PROGRESS',
    p_msg_id BIGINT DEFAULT NULL,
    p_max_attempts INT DEFAULT NULL
) RETURNS TABLE (
    domain TEXT,
    command_id UUID,
    command_type TEXT,
    status TEXT,
    attempts INT,
    max_attempts INT,
    msg_id BIGINT,
    correlation_id UUID,
    reply_queue TEXT,
    last_error_type TEXT,
    last_error_code TEXT,
    last_error_msg TEXT,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
) AS $$
DECLARE
    v_attempts INT;
    v_max_attempts INT;
    v_command_type TEXT;
    v_status TEXT;
    v_msg_id BIGINT;
    v_correlation_id UUID;
    v_reply_queue TEXT;
    v_last_error_type TEXT;
    v_last_error_code TEXT;
    v_last_error_msg TEXT;
    v_created_at TIMESTAMPTZ;
    v_updated_at TIMESTAMPTZ;
BEGIN
    -- Atomically update and get command metadata
    UPDATE command_bus_command c
    SET attempts = c.attempts + 1,
        status = p_new_status,
        updated_at = NOW()
    WHERE c.domain = p_domain
      AND c.command_id = p_command_id
      AND c.status NOT IN ('COMPLETED', 'CANCELED')
    RETURNING
        c.command_type, c.status, c.attempts, c.max_attempts, c.msg_id,
        c.correlation_id, c.reply_queue, c.last_error_type, c.last_error_code,
        c.last_error_msg, c.created_at, c.updated_at
    INTO
        v_command_type, v_status, v_attempts, v_max_attempts, v_msg_id,
        v_correlation_id, v_reply_queue, v_last_error_type, v_last_error_code,
        v_last_error_msg, v_created_at, v_updated_at;

    -- If no row updated, command not found or in terminal state
    IF NOT FOUND THEN
        RETURN;
    END IF;

    -- Insert audit event
    INSERT INTO command_bus_audit (domain, command_id, event_type, details_json)
    VALUES (
        p_domain,
        p_command_id,
        'RECEIVED',
        jsonb_build_object(
            'msg_id', COALESCE(p_msg_id, v_msg_id),
            'attempt', v_attempts,
            'max_attempts', COALESCE(p_max_attempts, v_max_attempts)
        )
    );

    -- Return the metadata
    RETURN QUERY SELECT
        p_domain,
        p_command_id,
        v_command_type,
        v_status,
        v_attempts,
        COALESCE(p_max_attempts, v_max_attempts),
        COALESCE(p_msg_id, v_msg_id),
        v_correlation_id,
        v_reply_queue,
        v_last_error_type,
        v_last_error_code,
        v_last_error_msg,
        v_created_at,
        v_updated_at;
END;
$$ LANGUAGE plpgsql;


-- sp_finish_command: Atomically finish a command (success or failure)
-- Combines: update status/error + insert audit
CREATE OR REPLACE FUNCTION sp_finish_command(
    p_domain TEXT,
    p_command_id UUID,
    p_status TEXT,
    p_event_type TEXT,
    p_error_type TEXT DEFAULT NULL,
    p_error_code TEXT DEFAULT NULL,
    p_error_msg TEXT DEFAULT NULL,
    p_details JSONB DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_found BOOLEAN;
BEGIN
    -- Update command metadata
    UPDATE command_bus_command
    SET status = p_status,
        last_error_type = COALESCE(p_error_type, last_error_type),
        last_error_code = COALESCE(p_error_code, last_error_code),
        last_error_msg = COALESCE(p_error_msg, last_error_msg),
        updated_at = NOW()
    WHERE domain = p_domain AND command_id = p_command_id;

    v_found := FOUND;

    -- Insert audit event (even if command not found, for debugging)
    INSERT INTO command_bus_audit (domain, command_id, event_type, details_json)
    VALUES (p_domain, p_command_id, p_event_type, p_details);

    RETURN v_found;
END;
$$ LANGUAGE plpgsql;


-- sp_fail_command: Handle transient failure with error update + audit
-- Used for retryable failures (before exhaustion)
CREATE OR REPLACE FUNCTION sp_fail_command(
    p_domain TEXT,
    p_command_id UUID,
    p_error_type TEXT,
    p_error_code TEXT,
    p_error_msg TEXT,
    p_attempt INT,
    p_max_attempts INT,
    p_msg_id BIGINT
) RETURNS BOOLEAN AS $$
BEGIN
    -- Update error info
    UPDATE command_bus_command
    SET last_error_type = p_error_type,
        last_error_code = p_error_code,
        last_error_msg = p_error_msg,
        updated_at = NOW()
    WHERE domain = p_domain AND command_id = p_command_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Insert audit event
    INSERT INTO command_bus_audit (domain, command_id, event_type, details_json)
    VALUES (
        p_domain,
        p_command_id,
        'FAILED',
        jsonb_build_object(
            'msg_id', p_msg_id,
            'attempt', p_attempt,
            'max_attempts', p_max_attempts,
            'error_type', p_error_type,
            'error_code', p_error_code,
            'error_msg', p_error_msg
        )
    );

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


-- Grant permissions (for non-superuser access if needed)
-- GRANT ALL ON ALL TABLES IN SCHEMA public TO your_app_user;
-- GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO your_app_user;
