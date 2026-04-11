-- Fix: OFAC screening silently returns zero matches due to float type mismatch.
--
-- Root cause: search_ofac_sdn() declares `trigram_similarity FLOAT` in its
-- RETURNS TABLE clause. Postgres FLOAT (no precision) is float8 (double
-- precision). But pg_trgm's similarity() returns real (float4). Postgres
-- refuses to execute the function:
--     "structure of query does not match function result type"
--     "Returned type real does not match expected type double precision in column 10."
--
-- The screening Python client catches this as an empty result set, making it
-- appear that every entity clears OFAC — a compliance-critical silent failure.
--
-- Fix: cast the two similarity() calls to double precision inside the CTE.
-- We cast rather than changing the RETURNS TABLE type because downstream
-- Python code expects float8 and changing the signature would break callers.
--
-- This is a CREATE OR REPLACE — atomic in-place swap, no data touched.

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
            similarity(e.sdn_name_normalized, normalized_query)::double precision AS trgm_sim,
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
            similarity(a.alternate_name_normalized, normalized_query)::double precision AS trgm_sim,
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
