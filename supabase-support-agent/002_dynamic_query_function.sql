-- ============================================
-- Dynamic read-only query function
-- Run this in Supabase SQL Editor
-- Used by the support agent for fallback queries
-- ============================================

CREATE OR REPLACE FUNCTION run_readonly_query(query_text TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  result JSONB;
BEGIN
  -- Only SELECT allowed
  IF NOT (UPPER(TRIM(query_text)) LIKE 'SELECT%') THEN
    RAISE EXCEPTION 'Only SELECT queries are allowed';
  END IF;

  -- Block mutations
  IF UPPER(query_text) ~ '(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXECUTE)' THEN
    RAISE EXCEPTION 'Mutation queries are not allowed';
  END IF;

  -- Block access to sensitive columns
  IF LOWER(query_text) ~ '(access_token|refresh_token|service_role|secret|password)' THEN
    RAISE EXCEPTION 'Access to sensitive columns is not allowed';
  END IF;

  EXECUTE 'SELECT jsonb_agg(row_to_json(t)) FROM (' || query_text || ') t'
  INTO result;

  RETURN COALESCE(result, '[]'::jsonb);
END;
$$;

-- Only service role can call this
REVOKE ALL ON FUNCTION run_readonly_query(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION run_readonly_query(TEXT) FROM anon;
REVOKE ALL ON FUNCTION run_readonly_query(TEXT) FROM authenticated;
