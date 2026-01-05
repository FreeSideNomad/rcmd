-- V002: E2E Test Schema
-- Creates the 'e2e' schema with test-specific tables
--
-- This migration is optional for production deployments.
-- It creates tables used by the E2E testing framework.

-- Create e2e schema
CREATE SCHEMA IF NOT EXISTS e2e;

-- Set search path for this migration
SET search_path TO e2e, public;

-- ============================================================================
-- Tables
-- ============================================================================

-- Test command table for E2E testing
-- Stores behavior specification for test commands
CREATE TABLE IF NOT EXISTS e2e.test_command (
    id SERIAL PRIMARY KEY,
    command_id UUID NOT NULL UNIQUE,
    payload JSONB NOT NULL DEFAULT '{}',
    behavior JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    attempts INTEGER DEFAULT 0,
    result JSONB
);

CREATE INDEX IF NOT EXISTS ix_test_command_command_id
    ON e2e.test_command(command_id);

CREATE INDEX IF NOT EXISTS ix_test_command_created_at
    ON e2e.test_command(created_at);

-- Configuration table for worker/retry settings
CREATE TABLE IF NOT EXISTS e2e.config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default configuration
INSERT INTO e2e.config (key, value) VALUES
    ('worker', '{"visibility_timeout": 30, "concurrency": 4, "poll_interval": 1.0, "batch_size": 10}'::jsonb),
    ('retry', '{"max_attempts": 3, "backoff_schedule": [10, 60, 300]}'::jsonb)
ON CONFLICT (key) DO NOTHING;


-- ============================================================================
-- PGMQ Queues for testing
-- These are created here for convenience during development/testing
-- ============================================================================

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

-- ============================================================================
-- Batch Summary Table for Reply Queue Aggregation
-- ============================================================================

-- Stores aggregated reply counts for e2e testing of reply queue functionality
CREATE TABLE IF NOT EXISTS e2e.batch_summary (
    id SERIAL PRIMARY KEY,
    batch_id UUID NOT NULL UNIQUE,
    domain TEXT NOT NULL DEFAULT 'e2e',
    total_expected INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    canceled_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS ix_batch_summary_batch_id
    ON e2e.batch_summary(batch_id);

CREATE INDEX IF NOT EXISTS ix_batch_summary_created_at
    ON e2e.batch_summary(created_at);
