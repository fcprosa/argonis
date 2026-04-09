-- =============================================================================
-- Phase 2: Evidence links & LLM cost tracking
-- =============================================================================
-- Changes:
--   1. evidence_links — make section_id + offsets nullable (pipeline doesn't
--      know section IDs / char offsets at insert time); add evidence_ref +
--      source_data columns.
--   2. llm_usage_log — new table for token/cost tracking per pipeline run.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. evidence_links — relax NOT NULL constraints & add new columns
-- ---------------------------------------------------------------------------

-- Make section_id nullable (pipeline inserts evidence_links without section ID)
ALTER TABLE evidence_links
    ALTER COLUMN section_id DROP NOT NULL;

-- Make char offsets nullable (offsets only set when front-end creates
-- inline citations; pipeline citations are sentence-level)
ALTER TABLE evidence_links
    ALTER COLUMN char_offset_start DROP NOT NULL,
    ALTER COLUMN char_offset_end   DROP NOT NULL;

-- Drop the check that depended on both offsets being non-null
ALTER TABLE evidence_links
    DROP CONSTRAINT IF EXISTS offsets_valid;

-- Re-add as a nullable-aware check: if either offset is set, both must be
-- set and end must be greater than start
ALTER TABLE evidence_links
    ADD CONSTRAINT offsets_both_or_neither CHECK (
        (char_offset_start IS NULL AND char_offset_end IS NULL)
        OR
        (char_offset_start IS NOT NULL AND char_offset_end IS NOT NULL
         AND char_offset_end > char_offset_start)
    );

-- evidence_ref: the EVID-XXX identifier the narrative cites inline
--   e.g. "EVID-001"  maps to the evidence item produced by the pipeline
ALTER TABLE evidence_links
    ADD COLUMN IF NOT EXISTS evidence_ref TEXT;

-- source_data: snapshot of the raw EvidenceItem so the front-end can render
-- a popover without a DB round-trip
ALTER TABLE evidence_links
    ADD COLUMN IF NOT EXISTS source_data JSONB;

-- Index for fast evidence_ref lookups (e.g. GET /narratives/{id} evidence panel)
CREATE INDEX IF NOT EXISTS idx_evidence_links_ref
    ON evidence_links (evidence_ref)
    WHERE evidence_ref IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. llm_usage_log — token & cost tracking
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS llm_usage_log (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID        REFERENCES organizations(id) ON DELETE SET NULL,
    case_id         UUID        REFERENCES cases(id) ON DELETE SET NULL,

    -- Which model was called
    model           TEXT        NOT NULL,

    -- Which pipeline step (always 'narrate' for now; future-proof for other LLM steps)
    step            TEXT        NOT NULL DEFAULT 'narrate',

    -- Token counts from Anthropic response
    input_tokens    INTEGER     NOT NULL CHECK (input_tokens >= 0),
    output_tokens   INTEGER     NOT NULL CHECK (output_tokens >= 0),

    -- Calculated cost at time of call (USD)
    cost_usd        NUMERIC(10, 6) NOT NULL CHECK (cost_usd >= 0),

    -- Wall-clock duration of the LLM call
    duration_ms     INTEGER     CHECK (duration_ms >= 0),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_org
    ON llm_usage_log (organization_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_llm_usage_case
    ON llm_usage_log (case_id)
    WHERE case_id IS NOT NULL;

-- RLS: org members can read their own usage
ALTER TABLE llm_usage_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "llm_usage_org_read" ON llm_usage_log
    FOR SELECT USING (organization_id = auth_org_id());
