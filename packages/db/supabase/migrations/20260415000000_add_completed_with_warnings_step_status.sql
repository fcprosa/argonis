-- Add 'completed_with_warnings' to the step_status enum.
--
-- The HIGH 4 partial failure policy (screening source timeouts) sets
-- investigation_steps.status to 'completed_with_warnings' in Python, but
-- the enum defined in 20260315000000_initial_schema.sql only has:
--     pending | running | completed | failed
--
-- This is a separate migration because 20260315000000 is already applied
-- in production — migration history is append-only.
--
-- Idempotent via IF NOT EXISTS: safe to re-run on any environment.

ALTER TYPE step_status ADD VALUE IF NOT EXISTS 'completed_with_warnings';
