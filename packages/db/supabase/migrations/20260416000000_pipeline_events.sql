-- pipeline_events: application-level meta-events from the investigation pipeline.
--
-- Distinct from audit_log (which is trigger-written row-level DML audit).
-- This table captures run-level events that don't correspond to a single
-- row INSERT/UPDATE/DELETE — things like "screening coverage was partial",
-- "KYC profile was missing", "firewall stripped N hallucinated citations".
--
-- Regulators need to be able to query these events by org, by case, and
-- by event type, so the indexing is designed for those access patterns.
--
-- Append-only. Writes happen from service-role Python code; reads are
-- scoped to the user's organization via RLS.

CREATE TYPE pipeline_event_type AS ENUM (
    'screening_partial',
    'screening_source_failed',
    'kyc_missing',
    'ofac_unavailable',
    'firewall_strip',
    'pipeline_failed',
    'pipeline_halted'
);

CREATE TABLE pipeline_events (
    id              UUID                PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID                NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    case_id         UUID                NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    user_id         UUID                REFERENCES users(id) ON DELETE SET NULL,
    event_type      pipeline_event_type NOT NULL,
    message         TEXT                NOT NULL,
    details         JSONB               NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW()
);

-- Indexes aligned to regulator and UI query patterns
CREATE INDEX idx_pipeline_events_org_time
    ON pipeline_events(organization_id, created_at DESC);
CREATE INDEX idx_pipeline_events_case
    ON pipeline_events(case_id, created_at DESC);
CREATE INDEX idx_pipeline_events_org_type_time
    ON pipeline_events(organization_id, event_type, created_at DESC);

-- Row-Level Security
ALTER TABLE pipeline_events ENABLE ROW LEVEL SECURITY;

-- Org members can read their own events
CREATE POLICY "pipeline_events_org_read" ON pipeline_events
    FOR SELECT USING (organization_id = auth_org_id());

-- Only service role can insert (Python pipeline code via service key).
-- No policy for INSERT/UPDATE/DELETE means they're denied for
-- authenticated users — service_role bypasses RLS and can write.

-- No UPDATE or DELETE policies — this table is append-only by design.
