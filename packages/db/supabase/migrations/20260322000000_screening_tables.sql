-- =============================================================================
-- Screening tables: OFAC SDN, OpenSanctions cache, adverse media
-- =============================================================================
-- Adds:
--   • pg_trgm + fuzzystrmatch extensions for fuzzy name matching
--   • ofac_sdn_entries — primary SDN names
--   • ofac_sdn_alternates — AKA / FKA aliases
--   • ofac_sdn_meta — single-row metadata (last refresh timestamp)
--   • search_ofac_sdn() — fuzzy search function returning ranked candidates
--   • screening_results.list_name column + index (additive)
--   • adverse_media_results — cached article URLs + Claude summaries

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

-- ---------------------------------------------------------------------------
-- OFAC SDN primary names
-- ---------------------------------------------------------------------------
CREATE TABLE ofac_sdn_entries (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    ent_num     INTEGER     NOT NULL,
    sdn_name    TEXT        NOT NULL,
    sdn_name_normalized TEXT NOT NULL,  -- lowercase, trimmed, diacritics stripped
    sdn_type    TEXT,                   -- 'individual', 'entity', 'vessel', 'aircraft'
    program     TEXT,
    title       TEXT,
    remarks     TEXT,
    source_url  TEXT        NOT NULL DEFAULT 'https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV',
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ent_num)
);

-- ---------------------------------------------------------------------------
-- OFAC SDN alternate names (AKA, FKA, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE ofac_sdn_alternates (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    ent_num         INTEGER NOT NULL REFERENCES ofac_sdn_entries(ent_num) ON DELETE CASCADE,
    alt_num         INTEGER NOT NULL,
    alternate_name  TEXT    NOT NULL,
    alternate_name_normalized TEXT NOT NULL,
    alternate_type  TEXT,   -- 'aka', 'fka', 'nka'
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ent_num, alt_num)
);

-- ---------------------------------------------------------------------------
-- OFAC SDN metadata (single-row table for tracking refresh state)
-- ---------------------------------------------------------------------------
CREATE TABLE ofac_sdn_meta (
    id              INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- enforce single row
    last_refreshed  TIMESTAMPTZ,
    entry_count     INTEGER NOT NULL DEFAULT 0,
    alt_count       INTEGER NOT NULL DEFAULT 0,
    source_hash     TEXT,   -- SHA-256 of the downloaded CSV to detect changes
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO ofac_sdn_meta (id) VALUES (1);

-- ---------------------------------------------------------------------------
-- Adverse media results — cached article URLs + Claude summaries
-- ---------------------------------------------------------------------------
CREATE TABLE adverse_media_results (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID        REFERENCES organizations(id) ON DELETE CASCADE,
    case_id         UUID        REFERENCES cases(id) ON DELETE CASCADE,
    entity_name     TEXT        NOT NULL,
    query_text      TEXT        NOT NULL,   -- the search query used
    article_url     TEXT        NOT NULL,
    article_title   TEXT,
    article_snippet TEXT,
    relevance_score FLOAT       CHECK (relevance_score BETWEEN 0 AND 1),
    claude_summary  TEXT,       -- Claude's assessment of relevance
    search_engine   TEXT        NOT NULL DEFAULT 'google_cse',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Add list_name to screening_results if not present
-- ---------------------------------------------------------------------------
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'screening_results' AND column_name = 'list_name'
    ) THEN
        ALTER TABLE screening_results ADD COLUMN list_name TEXT;
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'screening_results' AND column_name = 'screened_name'
    ) THEN
        ALTER TABLE screening_results ADD COLUMN screened_name TEXT;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

-- Trigram indexes for fuzzy name search (critical for performance)
CREATE INDEX idx_sdn_name_trgm
    ON ofac_sdn_entries USING gin (sdn_name_normalized gin_trgm_ops);

CREATE INDEX idx_sdn_alt_name_trgm
    ON ofac_sdn_alternates USING gin (alternate_name_normalized gin_trgm_ops);

-- B-tree for ent_num lookups
CREATE INDEX idx_sdn_ent_num ON ofac_sdn_entries(ent_num);
CREATE INDEX idx_sdn_alt_ent_num ON ofac_sdn_alternates(ent_num);

-- Adverse media
CREATE INDEX idx_adverse_media_case ON adverse_media_results(case_id);
CREATE INDEX idx_adverse_media_entity ON adverse_media_results(entity_name);
CREATE INDEX idx_adverse_media_org ON adverse_media_results(organization_id);

-- screening_results by list_name
CREATE INDEX idx_screening_list_name ON screening_results(list_name)
    WHERE list_name IS NOT NULL;
CREATE INDEX idx_screening_entity_name ON screening_results(entity_name);

-- ---------------------------------------------------------------------------
-- Fuzzy search function: search_ofac_sdn
-- ---------------------------------------------------------------------------
-- Returns the best matches across both primary and alternate names.
-- Uses pg_trgm similarity (good for typos/transliterations) combined with
-- Levenshtein distance. Caller passes a NORMALIZED query name.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION search_ofac_sdn(
    query_name      TEXT,
    min_similarity  FLOAT DEFAULT 0.25,  -- low threshold: Python re-scores with name normalization
    max_results     INTEGER DEFAULT 20
)
RETURNS TABLE (
    ent_num             INTEGER,
    matched_name        TEXT,
    matched_name_normalized TEXT,
    match_source        TEXT,       -- 'primary' or 'alternate'
    sdn_type            TEXT,
    program             TEXT,
    title               TEXT,
    remarks             TEXT,
    source_url          TEXT,
    trigram_similarity   FLOAT,
    levenshtein_dist    INTEGER,
    soundex_match       BOOLEAN
) AS $$
DECLARE
    normalized_query TEXT := lower(trim(query_name));
BEGIN
    RETURN QUERY
    WITH candidates AS (
        -- Search primary names
        SELECT
            e.ent_num,
            e.sdn_name          AS matched_name,
            e.sdn_name_normalized AS matched_name_normalized,
            'primary'::TEXT      AS match_source,
            e.sdn_type,
            e.program,
            e.title,
            e.remarks,
            e.source_url,
            similarity(e.sdn_name_normalized, normalized_query) AS trgm_sim,
            levenshtein(
                left(e.sdn_name_normalized, 255),
                left(normalized_query, 255)
            ) AS lev_dist,
            (soundex(e.sdn_name_normalized) = soundex(normalized_query)) AS sdx_match
        FROM ofac_sdn_entries e
        WHERE similarity(e.sdn_name_normalized, normalized_query) >= min_similarity
           OR soundex(e.sdn_name_normalized) = soundex(normalized_query)

        UNION ALL

        -- Search alternate names
        SELECT
            a.ent_num,
            a.alternate_name       AS matched_name,
            a.alternate_name_normalized AS matched_name_normalized,
            'alternate'::TEXT       AS match_source,
            e.sdn_type,
            e.program,
            e.title,
            e.remarks,
            e.source_url,
            similarity(a.alternate_name_normalized, normalized_query) AS trgm_sim,
            levenshtein(
                left(a.alternate_name_normalized, 255),
                left(normalized_query, 255)
            ) AS lev_dist,
            (soundex(a.alternate_name_normalized) = soundex(normalized_query)) AS sdx_match
        FROM ofac_sdn_alternates a
        JOIN ofac_sdn_entries e ON e.ent_num = a.ent_num
        WHERE similarity(a.alternate_name_normalized, normalized_query) >= min_similarity
           OR soundex(a.alternate_name_normalized) = soundex(normalized_query)
    )
    SELECT DISTINCT ON (c.ent_num)
        c.ent_num,
        c.matched_name,
        c.matched_name_normalized,
        c.match_source,
        c.sdn_type,
        c.program,
        c.title,
        c.remarks,
        c.source_url,
        c.trgm_sim,
        c.lev_dist,
        c.sdx_match
    FROM candidates c
    ORDER BY c.ent_num, c.trgm_sim DESC
    LIMIT max_results;
END;
$$ LANGUAGE plpgsql STABLE;

-- ---------------------------------------------------------------------------
-- RLS on new tables
-- ---------------------------------------------------------------------------
ALTER TABLE adverse_media_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY "adverse_media_org" ON adverse_media_results
    FOR ALL USING (organization_id = auth_org_id());

-- OFAC tables are public reference data — no RLS needed
-- (read by service role only, not by end users directly)

-- ---------------------------------------------------------------------------
-- Audit triggers for adverse_media_results
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_adverse_media_audit
    AFTER INSERT OR UPDATE OR DELETE ON adverse_media_results
    FOR EACH ROW EXECUTE FUNCTION write_audit_log();
