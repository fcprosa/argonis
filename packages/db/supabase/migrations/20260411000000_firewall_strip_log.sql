-- =============================================================================
-- Evidence firewall audit log
-- =============================================================================
-- Records which evidence IDs Claude cited but got stripped by the evidence
-- firewall (because they didn't exist in the evidence package).
--
-- strip_rate is a generated column: stripped_count / total_cited_count.
-- A rising strip_rate across runs indicates the prompt is encouraging
-- hallucination.  This table is the ground truth for that signal.

CREATE TABLE firewall_strip_log (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id              UUID        NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    section_id           UUID        NOT NULL REFERENCES narrative_sections(id) ON DELETE CASCADE,
    stripped_evidence_ids TEXT[]      NOT NULL,
    stripped_count        INTEGER     NOT NULL,
    total_cited_count     INTEGER     NOT NULL,
    strip_rate            NUMERIC     GENERATED ALWAYS AS (
        CASE WHEN total_cited_count = 0 THEN 0
             ELSE stripped_count::NUMERIC / total_cited_count::NUMERIC
        END
    ) STORED,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_firewall_strip_log_case_id
    ON firewall_strip_log(case_id);

CREATE INDEX idx_firewall_strip_log_strip_rate
    ON firewall_strip_log(strip_rate DESC);

-- RLS: org members can read rows for cases in their org.
-- Only service role can INSERT (no user-facing INSERT policy).
ALTER TABLE firewall_strip_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firewall_strip_log_org_read" ON firewall_strip_log
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM cases
            WHERE cases.id = firewall_strip_log.case_id
              AND cases.organization_id = auth_org_id()
        )
    );
