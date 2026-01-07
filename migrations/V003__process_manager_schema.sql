CREATE TABLE commandbus.process (
    domain VARCHAR(255) NOT NULL,
    process_id UUID NOT NULL,
    process_type VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'PENDING',
    current_step VARCHAR(255),
    state JSONB NOT NULL DEFAULT '{}',
    error_code VARCHAR(255),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,

    PRIMARY KEY (domain, process_id)
);

CREATE INDEX idx_process_type ON commandbus.process(domain, process_type);
CREATE INDEX idx_process_status ON commandbus.process(domain, status);
CREATE INDEX idx_process_created ON commandbus.process(created_at);

CREATE TABLE commandbus.process_audit (
    id BIGSERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL,
    process_id UUID NOT NULL,
    step_name VARCHAR(255) NOT NULL,
    command_id UUID NOT NULL,
    command_type VARCHAR(255) NOT NULL,
    command_data JSONB,
    sent_at TIMESTAMPTZ NOT NULL,
    reply_outcome VARCHAR(50),
    reply_data JSONB,
    received_at TIMESTAMPTZ,

    FOREIGN KEY (domain, process_id) REFERENCES commandbus.process(domain, process_id)
);

CREATE INDEX idx_process_audit_process ON commandbus.process_audit(domain, process_id);
CREATE INDEX idx_process_audit_command ON commandbus.process_audit(command_id);
