-- V004: Add failed_count column to batch table for BusinessRuleException support
-- This migration adds support for counting commands that failed due to business rule violations
-- (FAILED status) separately from canceled commands.

-- Add failed_count column to batch table
ALTER TABLE commandbus.batch
ADD COLUMN IF NOT EXISTS failed_count INT NOT NULL DEFAULT 0;

-- Drop existing function first (return type is changing)
DROP FUNCTION IF EXISTS commandbus.sp_refresh_batch_stats(TEXT, UUID);

-- Recreate sp_refresh_batch_stats with failed_count in return type
CREATE OR REPLACE FUNCTION commandbus.sp_refresh_batch_stats(
    p_domain TEXT,
    p_batch_id UUID
) RETURNS TABLE (
    completed_count BIGINT,
    failed_count BIGINT,
    canceled_count BIGINT,
    in_troubleshooting_count BIGINT,
    is_complete BOOLEAN
) AS $$
DECLARE
    v_total_count INT;
    v_batch_type TEXT;
    v_completed BIGINT;
    v_failed BIGINT;
    v_canceled BIGINT;
    v_in_tsq BIGINT;
    v_is_complete BOOLEAN;
BEGIN
    -- Get total count and batch_type from batch
    SELECT b.total_count, b.batch_type INTO v_total_count, v_batch_type
    FROM commandbus.batch b
    WHERE b.domain = p_domain AND b.batch_id = p_batch_id;

    IF v_total_count IS NULL THEN
        -- Batch not found
        RETURN;
    END IF;

    -- Calculate stats based on batch type
    IF v_batch_type = 'PROCESS' THEN
        -- Process batch: count from process table with TSQ detection via command join
        -- Success states: COMPLETED, COMPENSATED
        -- Failure states: FAILED, CANCELED (maps to canceled_count)
        -- Blocked in TSQ: non-terminal processes that have a command in IN_TROUBLESHOOTING_QUEUE
        SELECT
            COALESCE(SUM(CASE WHEN p.status IN ('COMPLETED', 'COMPENSATED') THEN 1 ELSE 0 END), 0),
            0,  -- Process batches don't use failed_count (business rule failures lead to CANCELED)
            COALESCE(SUM(CASE WHEN p.status IN ('FAILED', 'CANCELED') THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE
                WHEN p.status NOT IN ('COMPLETED', 'COMPENSATED', 'FAILED', 'CANCELED')
                     AND EXISTS (
                         SELECT 1 FROM commandbus.command c
                         WHERE c.correlation_id = p.process_id
                         AND c.status = 'IN_TROUBLESHOOTING_QUEUE'
                     )
                THEN 1 ELSE 0 END), 0)
        INTO v_completed, v_failed, v_canceled, v_in_tsq
        FROM commandbus.process p
        WHERE p.batch_id = p_batch_id;
    ELSE
        -- Command batch: count from command table
        -- FAILED status is for business rule violations (no retry, no TSQ)
        SELECT
            COALESCE(SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status = 'CANCELED' THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status = 'IN_TROUBLESHOOTING_QUEUE' THEN 1 ELSE 0 END), 0)
        INTO v_completed, v_failed, v_canceled, v_in_tsq
        FROM commandbus.command
        WHERE batch_id = p_batch_id;
    END IF;

    -- Check if batch is complete (all items in terminal state or blocked)
    -- For command batches, FAILED is also a terminal state
    v_is_complete := (v_completed + v_failed + v_canceled + v_in_tsq) >= v_total_count;

    -- Update batch table with calculated stats
    UPDATE commandbus.batch
    SET completed_count = v_completed,
        failed_count = v_failed,
        canceled_count = v_canceled,
        in_troubleshooting_count = v_in_tsq,
        status = CASE
            WHEN v_is_complete AND (v_failed > 0 OR v_canceled > 0 OR v_in_tsq > 0) THEN 'COMPLETED_WITH_FAILURES'
            WHEN v_is_complete THEN 'COMPLETED'
            WHEN status = 'PENDING' AND (v_completed + v_failed + v_canceled + v_in_tsq) > 0 THEN 'IN_PROGRESS'
            ELSE status
        END,
        completed_at = CASE
            WHEN v_is_complete AND completed_at IS NULL THEN NOW()
            ELSE completed_at
        END,
        started_at = CASE
            WHEN started_at IS NULL AND (v_completed + v_failed + v_canceled + v_in_tsq) > 0 THEN NOW()
            ELSE started_at
        END
    WHERE domain = p_domain AND batch_id = p_batch_id;

    -- Return the calculated stats
    RETURN QUERY SELECT v_completed, v_failed, v_canceled, v_in_tsq, v_is_complete;
END;
$$ LANGUAGE plpgsql;
