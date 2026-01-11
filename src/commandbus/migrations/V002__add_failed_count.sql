-- V002: Add failed_count column to batch table for BusinessRuleException support
-- This migration adds support for counting commands that failed due to business rule violations
-- (FAILED status) separately from canceled commands.

-- Add failed_count column to batch table
ALTER TABLE commandbus.batch
ADD COLUMN IF NOT EXISTS failed_count INT NOT NULL DEFAULT 0;

-- Update sp_finish_command to handle FAILED status
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
        ELSIF p_status = 'FAILED' THEN
            IF v_current_status = 'IN_PROGRESS' THEN
                -- Business rule failure: IN_PROGRESS -> FAILED
                v_update_type := 'failed';
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

-- Update sp_update_batch_counters to handle 'failed' update type
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

        WHEN 'failed' THEN
            UPDATE commandbus.batch
            SET failed_count = failed_count + 1
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
    -- Batch completion formula: completed + canceled + failed = total AND in_tsq = 0
    IF v_batch.completed_count + v_batch.canceled_count + v_batch.failed_count = v_batch.total_count
       AND v_batch.in_troubleshooting_count = 0 THEN
        v_is_complete := TRUE;

        -- Determine final status
        IF v_batch.canceled_count > 0 OR v_batch.failed_count > 0 THEN
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
                'failed_count', v_batch.failed_count,
                'canceled_count', v_batch.canceled_count
            )
        );
    END IF;

    RETURN v_is_complete;
END;
$$ LANGUAGE plpgsql;

-- Update sp_refresh_batch_stats to include failed_count
CREATE OR REPLACE FUNCTION commandbus.sp_refresh_batch_stats(
    p_domain TEXT,
    p_batch_id UUID
) RETURNS VOID AS $$
DECLARE
    v_stats RECORD;
BEGIN
    -- Calculate current stats from commands
    SELECT
        COUNT(*) FILTER (WHERE status = 'COMPLETED') as completed,
        COUNT(*) FILTER (WHERE status = 'FAILED') as failed,
        COUNT(*) FILTER (WHERE status = 'CANCELED') as canceled,
        COUNT(*) FILTER (WHERE status = 'IN_TROUBLESHOOTING_QUEUE') as in_tsq
    INTO v_stats
    FROM commandbus.command
    WHERE domain = p_domain AND batch_id = p_batch_id;

    -- Update batch with calculated values
    UPDATE commandbus.batch
    SET completed_count = v_stats.completed,
        failed_count = v_stats.failed,
        canceled_count = v_stats.canceled,
        in_troubleshooting_count = v_stats.in_tsq,
        updated_at = NOW()
    WHERE domain = p_domain AND batch_id = p_batch_id;
END;
$$ LANGUAGE plpgsql;
