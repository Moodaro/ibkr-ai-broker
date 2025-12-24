-- Initialize database schema for IBKR AI Broker
-- This script runs automatically when the PostgreSQL container starts

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- For text search

-- Create schemas
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS trading;

-- Set default search path
ALTER DATABASE ibkr_broker SET search_path TO public, audit, trading;

-- Grant permissions
GRANT ALL PRIVILEGES ON SCHEMA audit TO ibkr_user;
GRANT ALL PRIVILEGES ON SCHEMA trading TO ibkr_user;

-- Create audit events table (append-only)
CREATE TABLE IF NOT EXISTS audit.events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type VARCHAR(100) NOT NULL,
    correlation_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for audit queries
CREATE INDEX IF NOT EXISTS idx_audit_events_type ON audit.events(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_events_correlation ON audit.events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_events_timestamp ON audit.events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_events_data_gin ON audit.events USING GIN(data);

-- Prevent updates and deletes on audit table (append-only)
CREATE OR REPLACE FUNCTION audit.prevent_audit_modifications()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit events are append-only. Modifications not allowed.';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prevent_audit_update
    BEFORE UPDATE ON audit.events
    FOR EACH ROW EXECUTE FUNCTION audit.prevent_audit_modifications();

CREATE TRIGGER prevent_audit_delete
    BEFORE DELETE ON audit.events
    FOR EACH ROW EXECUTE FUNCTION audit.prevent_audit_modifications();

-- Create kill switch table
CREATE TABLE IF NOT EXISTS trading.kill_switch (
    id SERIAL PRIMARY KEY,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT,
    activated_by VARCHAR(100),
    activated_at TIMESTAMPTZ,
    deactivated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Insert initial kill switch state (disabled)
INSERT INTO trading.kill_switch (enabled, reason, created_at, updated_at)
VALUES (FALSE, 'Initial state', NOW(), NOW())
ON CONFLICT DO NOTHING;

-- Create approval tokens table
CREATE TABLE IF NOT EXISTS trading.approval_tokens (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_intent_hash VARCHAR(64) NOT NULL,
    token VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, used, expired, revoked
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_approval_tokens_token ON trading.approval_tokens(token);
CREATE INDEX IF NOT EXISTS idx_approval_tokens_status ON trading.approval_tokens(status);
CREATE INDEX IF NOT EXISTS idx_approval_tokens_expires ON trading.approval_tokens(expires_at);

-- Create order proposals table
CREATE TABLE IF NOT EXISTS trading.order_proposals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status VARCHAR(20) NOT NULL DEFAULT 'proposed', -- proposed, simulated, risk_approved, risk_rejected, approval_requested, approved, rejected, submitted, filled, cancelled
    order_intent JSONB NOT NULL,
    simulation_result JSONB,
    risk_decision JSONB,
    approval_token_id UUID REFERENCES trading.approval_tokens(id),
    broker_order_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_order_proposals_status ON trading.order_proposals(status);
CREATE INDEX IF NOT EXISTS idx_order_proposals_created ON trading.order_proposals(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_order_proposals_broker_order ON trading.order_proposals(broker_order_id);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Add triggers for updated_at
CREATE TRIGGER update_kill_switch_updated_at
    BEFORE UPDATE ON trading.kill_switch
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_order_proposals_updated_at
    BEFORE UPDATE ON trading.order_proposals
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Grant table permissions
GRANT SELECT, INSERT ON audit.events TO ibkr_user;
GRANT ALL PRIVILEGES ON trading.kill_switch TO ibkr_user;
GRANT ALL PRIVILEGES ON trading.approval_tokens TO ibkr_user;
GRANT ALL PRIVILEGES ON trading.order_proposals TO ibkr_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA trading TO ibkr_user;

COMMENT ON TABLE audit.events IS 'Append-only audit log for all system events';
COMMENT ON TABLE trading.kill_switch IS 'Emergency kill switch state';
COMMENT ON TABLE trading.approval_tokens IS 'Approval tokens for two-step commit';
COMMENT ON TABLE trading.order_proposals IS 'Order proposals and their lifecycle';
