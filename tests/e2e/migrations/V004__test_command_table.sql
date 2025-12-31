-- Test command table for E2E testing
-- Stores behavior specification for test commands

CREATE TABLE test_command (
    id SERIAL PRIMARY KEY,
    command_id UUID NOT NULL UNIQUE,
    payload JSONB NOT NULL DEFAULT '{}',
    behavior JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    attempts INTEGER DEFAULT 0,
    result JSONB
);

CREATE INDEX idx_test_command_command_id ON test_command(command_id);
CREATE INDEX idx_test_command_created_at ON test_command(created_at);

-- Configuration table for worker/retry settings
CREATE TABLE e2e_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Insert default configuration
INSERT INTO e2e_config (key, value) VALUES
    ('worker', '{"visibility_timeout": 30, "concurrency": 4, "poll_interval": 1.0, "batch_size": 10}'::jsonb),
    ('retry', '{"max_attempts": 3, "base_delay_ms": 1000, "max_delay_ms": 60000, "backoff_multiplier": 2.0}'::jsonb);
