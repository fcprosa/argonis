-- Track OFAC SDN refresh history for auditability and staleness monitoring.

CREATE TABLE ofac_refresh_log (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    refreshed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    entries_count   INTEGER     NOT NULL,
    alternates_count INTEGER    NOT NULL,
    source_url      TEXT        NOT NULL,
    triggered_by    UUID        REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ofac_refresh_log_refreshed_at
    ON ofac_refresh_log(refreshed_at DESC);

ALTER TABLE ofac_refresh_log ENABLE ROW LEVEL SECURITY;

-- Org admins can read refresh history
CREATE POLICY "ofac_refresh_log_select" ON ofac_refresh_log
    FOR SELECT USING (true);

-- Only service role (bypasses RLS) can insert; no user-facing INSERT policy
