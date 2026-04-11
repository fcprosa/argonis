-- OFAC SDN reference tables: enable RLS so PostgREST exposes them in the schema cache.
-- These tables contain public Treasury data — no tenant isolation needed.
-- Service role bypasses RLS for writes (refresh endpoint).
-- Authenticated users get SELECT access for fuzzy matching during screening.
--
-- Context: the original 20260322000000_screening_tables.sql created these tables
-- without RLS, assuming service-role-only access. That assumption was wrong —
-- PostgREST hides tables without RLS from its schema cache, which broke the
-- screening client's ability to query OFAC during pipeline Step 3.

ALTER TABLE ofac_sdn_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE ofac_sdn_alternates ENABLE ROW LEVEL SECURITY;
ALTER TABLE ofac_sdn_meta ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "ofac_sdn_entries_read" ON ofac_sdn_entries;
CREATE POLICY "ofac_sdn_entries_read" ON ofac_sdn_entries
    FOR SELECT USING (true);

DROP POLICY IF EXISTS "ofac_sdn_alternates_read" ON ofac_sdn_alternates;
CREATE POLICY "ofac_sdn_alternates_read" ON ofac_sdn_alternates
    FOR SELECT USING (true);

DROP POLICY IF EXISTS "ofac_sdn_meta_read" ON ofac_sdn_meta;
CREATE POLICY "ofac_sdn_meta_read" ON ofac_sdn_meta
    FOR SELECT USING (true);
