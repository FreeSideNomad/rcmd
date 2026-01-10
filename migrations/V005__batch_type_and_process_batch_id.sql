-- V005: Process Batch Support
--
-- Extends batch infrastructure to support process batches in addition to command batches.
--
-- Problem: When creating multiple processes via /processes/batch, there's no aggregate
-- completion tracking. Command batches don't help because a process spawns multiple
-- commands and command completion != process completion.
--
-- Solution: Add batch_type discriminator to batch table and batch_id to process table,
-- then update sp_refresh_batch_stats to handle both types.
--
-- Changes:
-- 1. Add batch_type column to batch table (default 'COMMAND' for backward compatibility)
-- 2. Add batch_id column to process table
-- 3. Add indexes for efficient process batch queries
-- 4. Update sp_refresh_batch_stats to handle process batches

-- ============================================================================
-- S089: Add batch_type to batch table
-- ============================================================================
ALTER TABLE commandbus.batch
ADD COLUMN batch_type TEXT NOT NULL DEFAULT 'COMMAND';

COMMENT ON COLUMN commandbus.batch.batch_type IS
'Type of batch: COMMAND for command batches, PROCESS for process batches.
Default is COMMAND for backward compatibility with existing batches.';

-- ============================================================================
-- S089: Add batch_id to process table
-- ============================================================================
ALTER TABLE commandbus.process
ADD COLUMN batch_id UUID;

-- Partial index for looking up processes by batch
CREATE INDEX ix_process_batch_id
ON commandbus.process (batch_id)
WHERE batch_id IS NOT NULL;

-- Index for efficient stats calculation by batch and status
CREATE INDEX ix_process_batch_status
ON commandbus.process (batch_id, status)
WHERE batch_id IS NOT NULL;

-- ============================================================================
-- S090: Update sp_refresh_batch_stats to handle process batches
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
    v_batch_type TEXT;
    v_completed BIGINT;
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
        -- Process batch: count from process table
        -- Success states: COMPLETED, COMPENSATED
        -- Failure states: FAILED, CANCELED (maps to canceled_count)
        -- In-progress: everything else (maps to in_troubleshooting_count for display)
        SELECT
            COALESCE(SUM(CASE WHEN status IN ('COMPLETED', 'COMPENSATED') THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status IN ('FAILED', 'CANCELED') THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status NOT IN ('COMPLETED', 'COMPENSATED', 'FAILED', 'CANCELED') THEN 1 ELSE 0 END), 0)
        INTO v_completed, v_canceled, v_in_tsq
        FROM commandbus.process
        WHERE batch_id = p_batch_id;
    ELSE
        -- Command batch: count from command table (existing behavior)
        SELECT
            COALESCE(SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status = 'CANCELED' THEN 1 ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN status = 'IN_TROUBLESHOOTING_QUEUE' THEN 1 ELSE 0 END), 0)
        INTO v_completed, v_canceled, v_in_tsq
        FROM commandbus.command
        WHERE batch_id = p_batch_id;
    END IF;

    -- Check if batch is complete (all items in terminal state)
    -- For process batches, in_tsq represents in-progress count
    IF v_batch_type = 'PROCESS' THEN
        v_is_complete := (v_completed + v_canceled) >= v_total_count;
    ELSE
        v_is_complete := (v_completed + v_canceled + v_in_tsq) >= v_total_count;
    END IF;

    -- Update batch table with calculated stats
    UPDATE commandbus.batch
    SET completed_count = v_completed,
        canceled_count = v_canceled,
        in_troubleshooting_count = v_in_tsq,
        status = CASE
            WHEN v_is_complete AND v_canceled > 0 THEN 'COMPLETED_WITH_FAILURES'
            WHEN v_is_complete THEN 'COMPLETED'
            WHEN status = 'PENDING' AND (v_completed + v_canceled + v_in_tsq) > 0 THEN 'IN_PROGRESS'
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

-- Update comment
COMMENT ON FUNCTION commandbus.sp_refresh_batch_stats IS
'Calculate and update batch statistics on demand.
For COMMAND batches: counts from command table (COMPLETED, CANCELED, IN_TROUBLESHOOTING_QUEUE).
For PROCESS batches: counts from process table (COMPLETED/COMPENSATED, FAILED/CANCELED, in-progress).
Called from UI when displaying batch details to avoid hot row contention during processing.
Returns: completed_count, canceled_count (or failed for process), in_troubleshooting_count (or in_progress), is_complete';
