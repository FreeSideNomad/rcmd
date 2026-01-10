-- V004: On-demand batch stats refresh
--
-- Problem: The hot row problem on batch counter updates causes severe lock contention
-- when many workers process commands from the same batch simultaneously.
--
-- Solution: Remove real-time counter updates from sp_finish_command and instead
-- calculate stats on-demand when the UI requests batch details.
--
-- Changes:
-- 1. Create sp_refresh_batch_stats to calculate and update batch stats from command table
-- 2. Modify sp_finish_command to skip the batch counter update call
-- 3. Add index on command(batch_id, status) for efficient counting

-- ============================================================================
-- Add index for efficient batch stats queries
-- ============================================================================
CREATE INDEX IF NOT EXISTS ix_command_batch_status
ON commandbus.command (batch_id, status)
WHERE batch_id IS NOT NULL;

-- ============================================================================
-- sp_refresh_batch_stats: Calculate batch stats from command table on demand
-- Called from UI when displaying batch details
-- ============================================================================
CREATE OR REPLACE FUNCTION commandbus.sp_refresh_batch_stats(
    p_domain TEXT,
    p_batch_id UUID
) RETURNS TABLE (
    completed_count BIGINT,
    canceled_count BIGINT,
    in_troubleshooting_count BIGINT,
    is_complete BOOLEAN
) AS $$
DECLARE
    v_total_count INT;
    v_completed BIGINT;
    v_canceled BIGINT;
    v_in_tsq BIGINT;
    v_is_complete BOOLEAN;
BEGIN
    -- Get total count from batch
    SELECT b.total_count INTO v_total_count
    FROM commandbus.batch b
    WHERE b.domain = p_domain AND b.batch_id = p_batch_id;

    IF v_total_count IS NULL THEN
        -- Batch not found
        RETURN;
    END IF;

    -- Calculate stats from command table
    SELECT
        COALESCE(SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN status = 'CANCELED' THEN 1 ELSE 0 END), 0),
        COALESCE(SUM(CASE WHEN status = 'IN_TROUBLESHOOTING_QUEUE' THEN 1 ELSE 0 END), 0)
    INTO v_completed, v_canceled, v_in_tsq
    FROM commandbus.command
    WHERE batch_id = p_batch_id;

    -- Check if batch is complete
    v_is_complete := (v_completed + v_canceled + v_in_tsq) >= v_total_count;

    -- Update batch table with calculated stats
    UPDATE commandbus.batch
    SET completed_count = v_completed,
        canceled_count = v_canceled,
        in_troubleshooting_count = v_in_tsq,
        status = CASE
            WHEN v_is_complete AND status != 'COMPLETED' THEN 'COMPLETED'
            WHEN NOT v_is_complete AND status = 'PENDING' AND (v_completed + v_canceled + v_in_tsq) > 0 THEN 'IN_PROGRESS'
            ELSE status
        END,
        completed_at = CASE
            WHEN v_is_complete AND completed_at IS NULL THEN NOW()
            ELSE completed_at
        END,
        started_at = CASE
            WHEN started_at IS NULL AND (v_completed + v_canceled + v_in_tsq) > 0 THEN NOW()
            ELSE started_at
        END
    WHERE domain = p_domain AND batch_id = p_batch_id;

    -- Return the calculated stats
    RETURN QUERY SELECT v_completed, v_canceled, v_in_tsq, v_is_complete;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Modify sp_finish_command to skip batch counter updates
-- The batch counters will be calculated on-demand via sp_refresh_batch_stats
-- ============================================================================
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

    -- NOTE: Batch counter updates removed to eliminate hot row contention.
    -- Batch stats are now calculated on-demand via sp_refresh_batch_stats.
    -- The p_batch_id parameter is kept for backward compatibility but not used.

    RETURN FALSE;  -- Always return FALSE since we no longer track batch completion here
END;
$$ LANGUAGE plpgsql;

-- Add comment explaining the change
COMMENT ON FUNCTION commandbus.sp_finish_command IS
'Finish a command (success or failure). Updates command status and creates audit entry.
Note: As of V004, batch counter updates are removed to eliminate hot row contention.
Batch stats are calculated on-demand via sp_refresh_batch_stats when viewing batch details.';

COMMENT ON FUNCTION commandbus.sp_refresh_batch_stats IS
'Calculate and update batch statistics from command table on demand.
Called from UI when displaying batch details to avoid hot row contention during processing.
Returns: completed_count, canceled_count, in_troubleshooting_count, is_complete';
