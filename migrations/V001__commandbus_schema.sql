-- V001: Command Bus Core Schema
-- Creates the 'commandbus' schema with all core tables and stored procedures
--
-- This migration consolidates all command bus database objects into a dedicated schema
-- for better organization and separation of concerns.

-- Enable PGMQ extension (required for message queuing)
CREATE EXTENSION IF NOT EXISTS pgmq;

-- Create commandbus schema
CREATE SCHEMA IF NOT EXISTS commandbus;

-- Set search path for this migration
SET search_path TO commandbus, pgmq, public;

-- ============================================================================
-- Tables
-- ============================================================================

-- Batch table (must be created before command table for FK reference)
CREATE TABLE IF NOT EXISTS commandbus.batch (
    domain                    TEXT NOT NULL,
    batch_id                  UUID NOT NULL,
    name                      TEXT NULL,
    custom_data               JSONB NULL,
    status                    TEXT NOT NULL DEFAULT 'PENDING',
    total_count               INT NOT NULL DEFAULT 0,
    completed_count           INT NOT NULL DEFAULT 0,
    canceled_count            INT NOT NULL DEFAULT 0,
    in_troubleshooting_count  INT NOT NULL DEFAULT 0,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at                TIMESTAMPTZ NULL,
    completed_at              TIMESTAMPTZ NULL,
    PRIMARY KEY (domain, batch_id)
);

CREATE INDEX IF NOT EXISTS ix_batch_status
    ON commandbus.batch(domain, status);

CREATE INDEX IF NOT EXISTS ix_batch_created
    ON commandbus.batch(domain, created_at DESC);

-- Command table (command metadata)
CREATE TABLE IF NOT EXISTS commandbus.command (
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
    correlation_id    UUID NULL,
    batch_id          UUID NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_command_domain_cmdid
    ON commandbus.command(domain, command_id);

CREATE INDEX IF NOT EXISTS ix_command_status_type
    ON commandbus.command(status, command_type);

CREATE INDEX IF NOT EXISTS ix_command_status_created
    ON commandbus.command(status, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_command_updated
    ON commandbus.command(updated_at);

CREATE INDEX IF NOT EXISTS ix_command_batch
    ON commandbus.command(domain, batch_id) WHERE batch_id IS NOT NULL;

-- Audit table (append-only)
CREATE TABLE IF NOT EXISTS commandbus.audit (
    audit_id      BIGSERIAL PRIMARY KEY,
    domain        TEXT NOT NULL,
    command_id    UUID NOT NULL,
    event_type    TEXT NOT NULL,
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details_json  JSONB NULL
);

CREATE INDEX IF NOT EXISTS ix_audit_cmdid_ts
    ON commandbus.audit(command_id, ts);

-- Optional payload archive
CREATE TABLE IF NOT EXISTS commandbus.payload_archive (
    domain        TEXT NOT NULL,
    command_id    UUID NOT NULL,
    payload_json  JSONB NOT NULL,
    archived_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY(domain, command_id)
);

-- ============================================================================
-- Stored Procedures
-- These combine command + audit operations into single DB calls for performance
-- ============================================================================

-- sp_receive_command: Atomically receive a command
-- Combines: get metadata + increment attempts + update status + insert audit + start batch
-- Returns NULL if command not found or in terminal state
CREATE OR REPLACE FUNCTION commandbus.sp_receive_command(
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
    updated_at TIMESTAMPTZ,
    batch_id UUID
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
    v_batch_id UUID;
BEGIN
    -- Atomically update and get command metadata
    UPDATE commandbus.command c
    SET attempts = c.attempts + 1,
        status = p_new_status,
        updated_at = NOW()
    WHERE c.domain = p_domain
      AND c.command_id = p_command_id
      AND c.status NOT IN ('COMPLETED', 'CANCELED')
    RETURNING
        c.command_type, c.status, c.attempts, c.max_attempts, c.msg_id,
        c.correlation_id, c.reply_queue, c.last_error_type, c.last_error_code,
        c.last_error_msg, c.created_at, c.updated_at, c.batch_id
    INTO
        v_command_type, v_status, v_attempts, v_max_attempts, v_msg_id,
        v_correlation_id, v_reply_queue, v_last_error_type, v_last_error_code,
        v_last_error_msg, v_created_at, v_updated_at, v_batch_id;

    -- If no row updated, command not found or in terminal state
    IF NOT FOUND THEN
        RETURN;
    END IF;

    -- Insert audit event
    INSERT INTO commandbus.audit (domain, command_id, event_type, details_json)
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

    -- Start batch if this command belongs to one (transitions PENDING -> IN_PROGRESS)
    IF v_batch_id IS NOT NULL THEN
        PERFORM commandbus.sp_start_batch(p_domain, v_batch_id);
    END IF;

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
        v_updated_at,
        v_batch_id;
END;
$$ LANGUAGE plpgsql;


-- sp_finish_command: Atomically finish a command (success or failure)
-- Combines: update status/error + insert audit + update batch counters
-- Returns is_batch_complete (TRUE if batch is now complete, for callback triggering)
--
-- Race condition fix: When a command takes longer than visibility timeout:
-- 1. Worker A receives command, starts processing (takes >30s)
-- 2. Visibility timeout expires, message redelivered
-- 3. Worker B receives same command, exhausts retries -> moves to TSQ
-- 4. Worker A finishes successfully -> calls complete
-- Solution: Check current status and use correct counter operation based on
-- the actual state transition (not just the target status).
CREATE OR REPLACE FUNCTION commandbus.sp_finish_command(
    p_domain TEXT,
    p_command_id UUID,
    p_status TEXT,
    p_event_type TEXT,
    p_error_type TEXT DEFAULT NULL,
    p_error_code TEXT DEFAULT NULL,
    p_error_msg TEXT DEFAULT NULL,
    p_details JSONB DEFAULT NULL,
    p_batch_id UUID DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_current_status TEXT;
    v_is_batch_complete BOOLEAN := FALSE;
    v_update_type TEXT;
BEGIN
    -- Get current status with row lock to prevent race conditions
    SELECT status INTO v_current_status
    FROM commandbus.command
    WHERE domain = p_domain AND command_id = p_command_id
    FOR UPDATE;

    -- If command not found, just log audit and return
    IF v_current_status IS NULL THEN
        INSERT INTO commandbus.audit (domain, command_id, event_type, details_json)
        VALUES (p_domain, p_command_id, p_event_type, p_details);
        RETURN FALSE;
    END IF;

    -- If command already in the target status, skip (idempotent)
    IF v_current_status = p_status THEN
        INSERT INTO commandbus.audit (domain, command_id, event_type, details_json)
        VALUES (p_domain, p_command_id, p_event_type, p_details);
        RETURN FALSE;
    END IF;

    -- Update command metadata
    UPDATE commandbus.command
    SET status = p_status,
        last_error_type = COALESCE(p_error_type, last_error_type),
        last_error_code = COALESCE(p_error_code, last_error_code),
        last_error_msg = COALESCE(p_error_msg, last_error_msg),
        updated_at = NOW()
    WHERE domain = p_domain AND command_id = p_command_id;

    -- Insert audit event
    INSERT INTO commandbus.audit (domain, command_id, event_type, details_json)
    VALUES (p_domain, p_command_id, p_event_type, p_details);

    -- Update batch counters if command belongs to a batch
    IF p_batch_id IS NOT NULL THEN
        -- Determine update type based on state transition
        IF p_status = 'COMPLETED' THEN
            IF v_current_status = 'IN_PROGRESS' THEN
                -- Normal completion: IN_PROGRESS -> COMPLETED
                v_update_type := 'complete';
            ELSIF v_current_status = 'IN_TROUBLESHOOTING_QUEUE' THEN
                -- Late completion after TSQ: decrement TSQ, increment completed
                v_update_type := 'tsq_complete';
            END IF;
        ELSIF p_status = 'IN_TROUBLESHOOTING_QUEUE' THEN
            IF v_current_status = 'IN_PROGRESS' THEN
                -- Normal TSQ move: IN_PROGRESS -> TSQ
                v_update_type := 'tsq_move';
            ELSIF v_current_status = 'COMPLETED' THEN
                -- Edge case: trying to move already completed command to TSQ - skip
                v_update_type := NULL;
            END IF;
        END IF;

        IF v_update_type IS NOT NULL THEN
            v_is_batch_complete := commandbus.sp_update_batch_counters(
                p_domain, p_batch_id, v_update_type
            );
        END IF;
    END IF;

    RETURN v_is_batch_complete;
END;
$$ LANGUAGE plpgsql;


-- sp_fail_command: Handle transient failure with error update + audit
-- Used for retryable failures (before exhaustion)
CREATE OR REPLACE FUNCTION commandbus.sp_fail_command(
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
    UPDATE commandbus.command
    SET last_error_type = p_error_type,
        last_error_code = p_error_code,
        last_error_msg = p_error_msg,
        updated_at = NOW()
    WHERE domain = p_domain AND command_id = p_command_id;

    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    -- Insert audit event
    INSERT INTO commandbus.audit (domain, command_id, event_type, details_json)
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


-- ============================================================================
-- Batch Status Tracking Stored Procedures
-- Consolidated batch counter updates with is_batch_complete return value
-- ============================================================================

-- sp_update_batch_counters: Central helper for updating batch counters
-- Called from sp_finish_command and TSQ operations
-- Returns TRUE if batch is now complete (for callback triggering)
--
-- update_type values:
--   'complete'     - Command completed successfully (completed_count++)
--   'tsq_move'     - Command moved to TSQ (in_troubleshooting_count++)
--   'tsq_complete' - Operator completed from TSQ (in_troubleshooting_count--, completed_count++)
--   'tsq_cancel'   - Operator canceled from TSQ (in_troubleshooting_count--, canceled_count++)
--   'tsq_retry'    - Operator retried from TSQ (in_troubleshooting_count--)
CREATE OR REPLACE FUNCTION commandbus.sp_update_batch_counters(
    p_domain TEXT,
    p_batch_id UUID,
    p_update_type TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_batch RECORD;
    v_is_complete BOOLEAN := FALSE;
BEGIN
    IF p_batch_id IS NULL THEN
        RETURN FALSE;
    END IF;

    -- Update counters based on update_type
    CASE p_update_type
        WHEN 'complete' THEN
            UPDATE commandbus.batch
            SET completed_count = completed_count + 1
            WHERE domain = p_domain AND batch_id = p_batch_id
            RETURNING * INTO v_batch;

        WHEN 'tsq_move' THEN
            UPDATE commandbus.batch
            SET in_troubleshooting_count = in_troubleshooting_count + 1
            WHERE domain = p_domain AND batch_id = p_batch_id
            RETURNING * INTO v_batch;

        WHEN 'tsq_complete' THEN
            UPDATE commandbus.batch
            SET in_troubleshooting_count = in_troubleshooting_count - 1,
                completed_count = completed_count + 1
            WHERE domain = p_domain AND batch_id = p_batch_id
            RETURNING * INTO v_batch;

        WHEN 'tsq_cancel' THEN
            UPDATE commandbus.batch
            SET in_troubleshooting_count = in_troubleshooting_count - 1,
                canceled_count = canceled_count + 1
            WHERE domain = p_domain AND batch_id = p_batch_id
            RETURNING * INTO v_batch;

        WHEN 'tsq_retry' THEN
            UPDATE commandbus.batch
            SET in_troubleshooting_count = in_troubleshooting_count - 1
            WHERE domain = p_domain AND batch_id = p_batch_id
            RETURNING * INTO v_batch;

        ELSE
            RAISE EXCEPTION 'Unknown update_type: %', p_update_type;
    END CASE;

    IF v_batch IS NULL THEN
        RETURN FALSE;
    END IF;

    -- Check if batch is now complete (all commands in terminal state, none in TSQ)
    -- Batch completion formula: completed + canceled = total AND in_tsq = 0
    IF v_batch.completed_count + v_batch.canceled_count = v_batch.total_count
       AND v_batch.in_troubleshooting_count = 0 THEN
        v_is_complete := TRUE;

        -- Determine final status
        IF v_batch.canceled_count > 0 THEN
            UPDATE commandbus.batch
            SET status = 'COMPLETED_WITH_FAILURES',
                completed_at = NOW()
            WHERE domain = p_domain AND batch_id = p_batch_id;
        ELSE
            UPDATE commandbus.batch
            SET status = 'COMPLETED',
                completed_at = NOW()
            WHERE domain = p_domain AND batch_id = p_batch_id;
        END IF;

        -- Record audit event for batch completion
        INSERT INTO commandbus.audit (domain, command_id, event_type, details_json)
        VALUES (
            p_domain,
            p_batch_id,
            'BATCH_COMPLETED',
            jsonb_build_object(
                'batch_id', p_batch_id,
                'total_count', v_batch.total_count,
                'completed_count', v_batch.completed_count,
                'canceled_count', v_batch.canceled_count
            )
        );
    END IF;

    RETURN v_is_complete;
END;
$$ LANGUAGE plpgsql;


-- sp_start_batch: Transition batch from PENDING to IN_PROGRESS on first command receive
-- Called from sp_receive_command when a batched command is first processed
CREATE OR REPLACE FUNCTION commandbus.sp_start_batch(
    p_domain TEXT,
    p_batch_id UUID
) RETURNS BOOLEAN AS $$
DECLARE
    v_batch RECORD;
BEGIN
    IF p_batch_id IS NULL THEN
        RETURN FALSE;
    END IF;

    -- Lock the batch row and check if it's still PENDING
    SELECT * INTO v_batch
    FROM commandbus.batch
    WHERE domain = p_domain AND batch_id = p_batch_id
    FOR UPDATE;

    IF v_batch IS NULL THEN
        RETURN FALSE;
    END IF;

    -- Only transition from PENDING to IN_PROGRESS
    IF v_batch.status = 'PENDING' THEN
        UPDATE commandbus.batch
        SET status = 'IN_PROGRESS',
            started_at = NOW()
        WHERE domain = p_domain AND batch_id = p_batch_id;

        -- Record audit event for batch start
        INSERT INTO commandbus.audit (domain, command_id, event_type, details_json)
        VALUES (
            p_domain,
            p_batch_id,  -- Use batch_id as command_id for batch events
            'BATCH_STARTED',
            jsonb_build_object('batch_id', p_batch_id)
        );

        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- Troubleshooting Queue (TSQ) Stored Procedures
-- These are called by operators to complete/cancel/retry commands from TSQ
-- They return is_batch_complete for callback triggering
-- ============================================================================

-- sp_tsq_complete: Operator completes a command from TSQ
-- Returns is_batch_complete flag for callback triggering
CREATE OR REPLACE FUNCTION commandbus.sp_tsq_complete(
    p_domain TEXT,
    p_batch_id UUID
) RETURNS BOOLEAN AS $$
BEGIN
    IF p_batch_id IS NULL THEN
        RETURN FALSE;
    END IF;
    RETURN commandbus.sp_update_batch_counters(p_domain, p_batch_id, 'tsq_complete');
END;
$$ LANGUAGE plpgsql;


-- sp_tsq_cancel: Operator cancels a command from TSQ
-- Returns is_batch_complete flag for callback triggering
CREATE OR REPLACE FUNCTION commandbus.sp_tsq_cancel(
    p_domain TEXT,
    p_batch_id UUID
) RETURNS BOOLEAN AS $$
BEGIN
    IF p_batch_id IS NULL THEN
        RETURN FALSE;
    END IF;
    RETURN commandbus.sp_update_batch_counters(p_domain, p_batch_id, 'tsq_cancel');
END;
$$ LANGUAGE plpgsql;


-- sp_tsq_retry: Operator retries a command from TSQ
-- Note: Retry never completes a batch (command goes back to queue)
-- Returns FALSE always since retry cannot complete a batch
CREATE OR REPLACE FUNCTION commandbus.sp_tsq_retry(
    p_domain TEXT,
    p_batch_id UUID
) RETURNS BOOLEAN AS $$
BEGIN
    IF p_batch_id IS NULL THEN
        RETURN FALSE;
    END IF;
    -- sp_update_batch_counters will always return FALSE for tsq_retry
    -- because it decrements in_troubleshooting_count without adding to terminal counts
    RETURN commandbus.sp_update_batch_counters(p_domain, p_batch_id, 'tsq_retry');
END;
$$ LANGUAGE plpgsql;
