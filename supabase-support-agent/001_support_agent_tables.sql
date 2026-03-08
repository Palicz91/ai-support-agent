-- ============================================
-- Supabase Support Agent - Table Migration
-- Run this in Supabase SQL Editor
-- ============================================

-- 1. Error codes table
CREATE TABLE IF NOT EXISTS error_codes (
  id SERIAL PRIMARY KEY,
  code TEXT UNIQUE NOT NULL,               -- e.g. ERR_AUTH_001
  component TEXT NOT NULL,                 -- e.g. LoginForm, PaymentProcessor
  source TEXT NOT NULL DEFAULT 'backend',  -- 'frontend' or 'backend'
  trigger_condition TEXT NOT NULL,         -- what causes this error
  user_message TEXT,                       -- what the end user sees
  internal_description TEXT NOT NULL,      -- detailed explanation for support
  severity TEXT NOT NULL DEFAULT 'medium'
    CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  suggested_fix TEXT,                      -- actionable fix instructions
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Agent interaction logs
CREATE TABLE IF NOT EXISTS agent_logs (
  id SERIAL PRIMARY KEY,
  telegram_user_id BIGINT,
  user_name TEXT,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  queries_run JSONB DEFAULT '[]',
  tools_used JSONB DEFAULT '[]',
  escalated BOOLEAN DEFAULT false,
  escalation_reason TEXT,
  confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
  response_time_ms INTEGER,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. Chat history (conversation memory)
CREATE TABLE IF NOT EXISTS chat_history (
  id SERIAL PRIMARY KEY,
  telegram_user_id BIGINT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_chat_history_user_time
  ON chat_history (telegram_user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_logs_time
  ON agent_logs (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_error_codes_code
  ON error_codes (code);

-- Auto-update timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER error_codes_updated_at
  BEFORE UPDATE ON error_codes
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at();

-- RLS: block anonymous access (service role bypasses RLS)
ALTER TABLE error_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "No anon access" ON error_codes FOR ALL TO anon USING (false);
CREATE POLICY "No anon access" ON agent_logs FOR ALL TO anon USING (false);
CREATE POLICY "No anon access" ON chat_history FOR ALL TO anon USING (false);
