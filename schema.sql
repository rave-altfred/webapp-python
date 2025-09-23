-- Database Schema for Webapp Statistics Dashboard
-- This file contains the PostgreSQL database schema

-- Create database (run as superuser if needed)
-- CREATE DATABASE webapp_db;

-- Connect to the database
-- \c webapp_db;

-- Create extensions if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP WITH TIME ZONE
);

-- User activities table for tracking user actions
CREATE TABLE IF NOT EXISTS user_activities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,
    description TEXT,
    ip_address INET,
    user_agent TEXT,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Sessions table for managing user sessions
CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    session_token VARCHAR(255) UNIQUE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    ip_address INET,
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Application logs table
CREATE TABLE IF NOT EXISTS application_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    level VARCHAR(20) NOT NULL,
    message TEXT NOT NULL,
    module VARCHAR(100),
    function_name VARCHAR(100),
    line_number INTEGER,
    user_id UUID REFERENCES users(id),
    request_id VARCHAR(50),
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- System metrics table for storing application metrics
CREATE TABLE IF NOT EXISTS system_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    metric_name VARCHAR(100) NOT NULL,
    metric_value NUMERIC NOT NULL,
    metric_unit VARCHAR(20),
    tags JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- API endpoints usage statistics
CREATE TABLE IF NOT EXISTS api_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(10) NOT NULL,
    status_code INTEGER NOT NULL,
    response_time_ms INTEGER,
    user_id UUID REFERENCES users(id),
    ip_address INET,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);

CREATE INDEX IF NOT EXISTS idx_user_activities_user_id ON user_activities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_activities_type ON user_activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_user_activities_created_at ON user_activities(created_at);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_token ON user_sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);

CREATE INDEX IF NOT EXISTS idx_application_logs_level ON application_logs(level);
CREATE INDEX IF NOT EXISTS idx_application_logs_created_at ON application_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_application_logs_user_id ON application_logs(user_id);

CREATE INDEX IF NOT EXISTS idx_system_metrics_name ON system_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_system_metrics_created_at ON system_metrics(created_at);

CREATE INDEX IF NOT EXISTS idx_api_usage_endpoint ON api_usage(endpoint);
CREATE INDEX IF NOT EXISTS idx_api_usage_created_at ON api_usage(created_at);
CREATE INDEX IF NOT EXISTS idx_api_usage_status_code ON api_usage(status_code);

-- Create function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Add triggers for updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Insert sample data for testing
INSERT INTO users (username, email, password_hash, first_name, last_name, is_verified) 
VALUES 
    ('admin', 'admin@example.com', '$2b$12$example_hash_here', 'Admin', 'User', true),
    ('testuser', 'test@example.com', '$2b$12$example_hash_here', 'Test', 'User', true),
    ('john.doe', 'john@example.com', '$2b$12$example_hash_here', 'John', 'Doe', false)
ON CONFLICT (username) DO NOTHING;

-- Insert sample activities
INSERT INTO user_activities (user_id, activity_type, description, ip_address)
SELECT 
    u.id,
    (ARRAY['login', 'logout', 'profile_update', 'password_change', 'data_export'])[floor(random() * 5 + 1)],
    'Sample activity for testing',
    ('192.168.1.' || floor(random() * 254 + 1))::inet
FROM users u, generate_series(1, 50) 
ON CONFLICT DO NOTHING;

-- Insert sample system metrics
INSERT INTO system_metrics (metric_name, metric_value, metric_unit, tags)
VALUES
    ('cpu_usage_percent', 45.5, '%', '{"host": "web01"}'),
    ('memory_usage_percent', 67.2, '%', '{"host": "web01"}'),
    ('disk_usage_percent', 23.1, '%', '{"host": "web01", "mount": "/"}'),
    ('response_time_avg', 245, 'ms', '{"endpoint": "/api/stats"}'),
    ('active_sessions', 15, 'count', '{"type": "user_sessions"}')
ON CONFLICT DO NOTHING;

-- Insert sample API usage data
INSERT INTO api_usage (endpoint, method, status_code, response_time_ms, ip_address)
SELECT 
    (ARRAY['/api/stats', '/api/valkey', '/api/postgres', '/health', '/'])[floor(random() * 5 + 1)],
    (ARRAY['GET', 'POST', 'PUT'])[floor(random() * 3 + 1)],
    (ARRAY[200, 201, 400, 404, 500])[floor(random() * 5 + 1)],
    floor(random() * 1000 + 50)::integer,
    ('10.0.0.' || floor(random() * 254 + 1))::inet
FROM generate_series(1, 100)
ON CONFLICT DO NOTHING;

-- Create a view for recent activity summary
CREATE OR REPLACE VIEW recent_activity_summary AS
SELECT 
    DATE_TRUNC('hour', created_at) as hour,
    activity_type,
    COUNT(*) as activity_count
FROM user_activities 
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', created_at), activity_type
ORDER BY hour DESC, activity_count DESC;

-- Create a view for API usage summary
CREATE OR REPLACE VIEW api_usage_summary AS
SELECT 
    endpoint,
    method,
    COUNT(*) as request_count,
    AVG(response_time_ms) as avg_response_time,
    COUNT(*) FILTER (WHERE status_code >= 400) as error_count
FROM api_usage
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY endpoint, method
ORDER BY request_count DESC;

-- Grant permissions (adjust as needed for your setup)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO webapp_user;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO webapp_user;