-- =============================================================================
-- Argonis: Initial Schema
-- =============================================================================
-- Design notes:
--   • organization_id is denormalized onto EVERY table for O(1) RLS evaluation.
--   • evidence_links uses char offsets + sentence_text snapshot so citations
--     survive section edits. Exactly one source FK must be set (CHECK enforced).
--   • narratives are immutable versions: each row IS a version (case_id, version UNIQUE).
--   • audit_log is append-only, populated exclusively by triggers.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- Enum types
-- ---------------------------------------------------------------------------
CREATE TYPE user_role            AS ENUM ('admin', 'analyst', 'reviewer');
CREATE TYPE alert_status         AS ENUM ('new', 'reviewing', 'escalated', 'closed');
CREATE TYPE alert_severity       AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE case_status          AS ENUM ('open', 'in_review', 'escalated', 'closed');
CREATE TYPE step_status          AS ENUM ('pending', 'running', 'completed', 'failed');
CREATE TYPE screening_status     AS ENUM ('pending', 'confirmed', 'dismissed');
CREATE TYPE narrative_status     AS ENUM ('draft', 'in_review', 'approved', 'rejected');
CREATE TYPE approval_status      AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE evidence_source_type AS ENUM ('investigation_step', 'screening_result', 'alert', 'external');
CREATE TYPE audit_action         AS ENUM ('INSERT', 'UPDATE', 'DELETE');

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

-- organizations ---------------------------------------------------------------
CREATE TABLE organizations (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name       TEXT        NOT NULL,
    slug       TEXT        NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- users (extends auth.users) --------------------------------------------------
CREATE TABLE users (
    id              UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    organization_id UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           TEXT        NOT NULL,
    full_name       TEXT,
    role            user_role   NOT NULL DEFAULT 'analyst',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Helper: get calling user's organization_id without a join in every policy.
-- SECURITY DEFINER intentionally bypasses RLS on users (reads own row only).
CREATE OR REPLACE FUNCTION auth_org_id()
RETURNS UUID
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT organization_id FROM users WHERE id = auth.uid()
$$;

-- alerts ----------------------------------------------------------------------
CREATE TABLE alerts (
    id              UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID           NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title           TEXT           NOT NULL,
    description     TEXT,
    status          alert_status   NOT NULL DEFAULT 'new',
    severity        alert_severity NOT NULL DEFAULT 'medium',
    source          TEXT           NOT NULL,
    raw_data        JSONB,
    created_by      UUID           REFERENCES users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

-- cases -----------------------------------------------------------------------
CREATE TABLE cases (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    alert_id        UUID        REFERENCES alerts(id) ON DELETE SET NULL,
    title           TEXT        NOT NULL,
    description     TEXT,
    status          case_status NOT NULL DEFAULT 'open',
    assigned_to     UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_by      UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- investigation_steps ---------------------------------------------------------
-- source_data: raw evidence blob from any external system or agent tool call.
-- confidence_score: 0.000–1.000; enforced by CHECK.
CREATE TABLE investigation_steps (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    case_id          UUID        NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    name             TEXT        NOT NULL,
    description      TEXT,
    status           step_status NOT NULL DEFAULT 'pending',
    source_data      JSONB,
    confidence_score NUMERIC(4,3)
        CONSTRAINT confidence_range CHECK (confidence_score BETWEEN 0 AND 1),
    created_by       UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- screening_results -----------------------------------------------------------
CREATE TABLE screening_results (
    id               UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID              NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    case_id          UUID              NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    entity_name      TEXT              NOT NULL,
    match_confidence NUMERIC(4,3)      NOT NULL
        CONSTRAINT match_confidence_range CHECK (match_confidence BETWEEN 0 AND 1),
    source_url       TEXT,
    match_data       JSONB,
    status           screening_status  NOT NULL DEFAULT 'pending',
    reviewed_by      UUID              REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ       NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ       NOT NULL DEFAULT NOW()
);

-- narratives (versioned) ------------------------------------------------------
-- Each row IS an immutable version. parent_id → previous version.
-- UNIQUE(case_id, version) prevents duplicate version numbers per case.
CREATE TABLE narratives (
    id              UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID             NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    case_id         UUID             NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    version         INTEGER          NOT NULL DEFAULT 1
        CONSTRAINT version_positive CHECK (version > 0),
    title           TEXT             NOT NULL,
    status          narrative_status NOT NULL DEFAULT 'draft',
    parent_id       UUID             REFERENCES narratives(id) ON DELETE SET NULL,
    created_by      UUID             NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    UNIQUE (case_id, version)
);

-- narrative_sections ----------------------------------------------------------
-- organization_id denormalized here so RLS on this table needs no join.
-- Each section has its own approval_status (section-level approval workflow).
CREATE TABLE narrative_sections (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID            NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    narrative_id    UUID            NOT NULL REFERENCES narratives(id) ON DELETE CASCADE,
    section_key     TEXT            NOT NULL,   -- e.g. 'executive_summary', 'findings'
    title           TEXT            NOT NULL,
    content         TEXT            NOT NULL DEFAULT '',
    order_index     INTEGER         NOT NULL DEFAULT 0,
    approval_status approval_status NOT NULL DEFAULT 'pending',
    approved_by     UUID            REFERENCES users(id) ON DELETE SET NULL,
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (narrative_id, section_key)
);

-- evidence_links --------------------------------------------------------------
-- THE CORE TABLE for inline fact-verification.
--
-- Maps a specific text span within a narrative section to exactly one evidence
-- source. Rules:
--   1. char_offset_start/end identify the cited span inside section.content.
--   2. sentence_text is a snapshot of that span at link-creation time — survives
--      subsequent section edits and enables display without re-fetching content.
--   3. Exactly one source FK must be non-null, enforced by evidence_source_check.
--      source_type is a redundant discriminator kept for fast filtering.
--
-- Source types:
--   investigation_step → investigation_steps.id
--   screening_result   → screening_results.id
--   alert              → alerts.id
--   external           → external_url (no FK, URL to external document)
CREATE TABLE evidence_links (
    id                    UUID                PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id       UUID                NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    narrative_id          UUID                NOT NULL REFERENCES narratives(id) ON DELETE CASCADE,
    section_id            UUID                NOT NULL REFERENCES narrative_sections(id) ON DELETE CASCADE,

    -- The cited text span
    sentence_text         TEXT                NOT NULL,  -- snapshot at link time
    char_offset_start     INTEGER             NOT NULL,
    char_offset_end       INTEGER             NOT NULL,
    CONSTRAINT offsets_valid CHECK (char_offset_end > char_offset_start),

    -- Source discriminator
    source_type           evidence_source_type NOT NULL,

    -- Source FKs — exactly one must be set (see evidence_source_check below)
    investigation_step_id UUID REFERENCES investigation_steps(id) ON DELETE CASCADE,
    screening_result_id   UUID REFERENCES screening_results(id)   ON DELETE CASCADE,
    alert_id              UUID REFERENCES alerts(id)               ON DELETE CASCADE,
    external_url          TEXT,
    external_title        TEXT,

    -- Enforce: source_type matches the one non-null FK
    CONSTRAINT evidence_source_check CHECK (
        (source_type = 'investigation_step'
            AND investigation_step_id IS NOT NULL
            AND screening_result_id   IS NULL
            AND alert_id              IS NULL
            AND external_url          IS NULL)
        OR
        (source_type = 'screening_result'
            AND screening_result_id   IS NOT NULL
            AND investigation_step_id IS NULL
            AND alert_id              IS NULL
            AND external_url          IS NULL)
        OR
        (source_type = 'alert'
            AND alert_id              IS NOT NULL
            AND investigation_step_id IS NULL
            AND screening_result_id   IS NULL
            AND external_url          IS NULL)
        OR
        (source_type = 'external'
            AND external_url          IS NOT NULL
            AND investigation_step_id IS NULL
            AND screening_result_id   IS NULL
            AND alert_id              IS NULL)
    ),

    created_by  UUID        REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- No updated_at: evidence_links are immutable. Delete + re-create on edit.
);

-- audit_log -------------------------------------------------------------------
-- Append-only. Written only by triggers (no direct INSERT allowed via RLS).
CREATE TABLE audit_log (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID         REFERENCES organizations(id) ON DELETE SET NULL,
    user_id         UUID         REFERENCES users(id) ON DELETE SET NULL,
    action          audit_action NOT NULL,
    table_name      TEXT         NOT NULL,
    record_id       UUID         NOT NULL,
    old_data        JSONB,
    new_data        JSONB,
    ip_address      INET,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX idx_users_org                  ON users(organization_id);

CREATE INDEX idx_alerts_org                 ON alerts(organization_id);
CREATE INDEX idx_alerts_org_status          ON alerts(organization_id, status);

CREATE INDEX idx_cases_org                  ON cases(organization_id);
CREATE INDEX idx_cases_alert                ON cases(alert_id)       WHERE alert_id IS NOT NULL;
CREATE INDEX idx_cases_assigned             ON cases(assigned_to)    WHERE assigned_to IS NOT NULL;
CREATE INDEX idx_cases_org_status           ON cases(organization_id, status);

CREATE INDEX idx_steps_case                 ON investigation_steps(case_id);
CREATE INDEX idx_steps_org                  ON investigation_steps(organization_id);

CREATE INDEX idx_screening_case             ON screening_results(case_id);
CREATE INDEX idx_screening_org_status       ON screening_results(organization_id, status);

CREATE INDEX idx_narratives_case            ON narratives(case_id);
CREATE INDEX idx_narratives_org             ON narratives(organization_id);

CREATE INDEX idx_sections_narrative         ON narrative_sections(narrative_id);
CREATE INDEX idx_sections_approval          ON narrative_sections(narrative_id, approval_status);

CREATE INDEX idx_evidence_links_narrative   ON evidence_links(narrative_id);
CREATE INDEX idx_evidence_links_section     ON evidence_links(section_id);
-- Partial indexes per source type for fast evidence lookups
CREATE INDEX idx_evidence_links_step        ON evidence_links(investigation_step_id)
    WHERE investigation_step_id IS NOT NULL;
CREATE INDEX idx_evidence_links_screening   ON evidence_links(screening_result_id)
    WHERE screening_result_id IS NOT NULL;
CREATE INDEX idx_evidence_links_alert       ON evidence_links(alert_id)
    WHERE alert_id IS NOT NULL;

CREATE INDEX idx_audit_log_org_time         ON audit_log(organization_id, created_at DESC);
CREATE INDEX idx_audit_log_record           ON audit_log(table_name, record_id);
CREATE INDEX idx_audit_log_user             ON audit_log(user_id, created_at DESC)
    WHERE user_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- updated_at auto-maintenance
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_alerts_updated_at
    BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_cases_updated_at
    BEFORE UPDATE ON cases
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_investigation_steps_updated_at
    BEFORE UPDATE ON investigation_steps
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_screening_results_updated_at
    BEFORE UPDATE ON screening_results
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_narratives_updated_at
    BEFORE UPDATE ON narratives
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_narrative_sections_updated_at
    BEFORE UPDATE ON narrative_sections
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- Audit log trigger
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION write_audit_log()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_record_id UUID;
    v_org_id    UUID;
BEGIN
    -- Resolve record_id and org_id from whichever row exists
    IF TG_OP = 'DELETE' THEN
        v_record_id := OLD.id;
        -- organization_id column exists on all audited tables
        v_org_id := OLD.organization_id;
    ELSE
        v_record_id := NEW.id;
        v_org_id    := NEW.organization_id;
    END IF;

    INSERT INTO audit_log (
        organization_id, user_id, action, table_name, record_id, old_data, new_data
    ) VALUES (
        v_org_id,
        auth.uid(),
        TG_OP::audit_action,
        TG_TABLE_NAME,
        v_record_id,
        CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) ELSE NULL END,
        CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) ELSE NULL END
    );

    RETURN COALESCE(NEW, OLD);
END;
$$;

-- Apply audit triggers to all tables that carry business state
CREATE TRIGGER audit_cases
    AFTER INSERT OR UPDATE OR DELETE ON cases
    FOR EACH ROW EXECUTE FUNCTION write_audit_log();

CREATE TRIGGER audit_investigation_steps
    AFTER INSERT OR UPDATE OR DELETE ON investigation_steps
    FOR EACH ROW EXECUTE FUNCTION write_audit_log();

CREATE TRIGGER audit_screening_results
    AFTER INSERT OR UPDATE OR DELETE ON screening_results
    FOR EACH ROW EXECUTE FUNCTION write_audit_log();

CREATE TRIGGER audit_narratives
    AFTER INSERT OR UPDATE OR DELETE ON narratives
    FOR EACH ROW EXECUTE FUNCTION write_audit_log();

CREATE TRIGGER audit_narrative_sections
    AFTER INSERT OR UPDATE OR DELETE ON narrative_sections
    FOR EACH ROW EXECUTE FUNCTION write_audit_log();

CREATE TRIGGER audit_evidence_links
    AFTER INSERT OR DELETE ON evidence_links
    FOR EACH ROW EXECUTE FUNCTION write_audit_log();

-- ---------------------------------------------------------------------------
-- Row-Level Security
-- ---------------------------------------------------------------------------
ALTER TABLE organizations      ENABLE ROW LEVEL SECURITY;
ALTER TABLE users              ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts             ENABLE ROW LEVEL SECURITY;
ALTER TABLE cases              ENABLE ROW LEVEL SECURITY;
ALTER TABLE investigation_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE screening_results  ENABLE ROW LEVEL SECURITY;
ALTER TABLE narratives         ENABLE ROW LEVEL SECURITY;
ALTER TABLE narrative_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_links     ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log          ENABLE ROW LEVEL SECURITY;

-- organizations: member sees own org only
CREATE POLICY "org_own" ON organizations
    FOR ALL USING (id = auth_org_id());

-- users: members see peers in the same org
CREATE POLICY "users_same_org" ON users
    FOR ALL USING (organization_id = auth_org_id());

-- alerts
CREATE POLICY "alerts_org" ON alerts
    FOR ALL USING (organization_id = auth_org_id());

-- cases
CREATE POLICY "cases_org" ON cases
    FOR ALL USING (organization_id = auth_org_id());

-- investigation_steps
CREATE POLICY "steps_org" ON investigation_steps
    FOR ALL USING (organization_id = auth_org_id());

-- screening_results
CREATE POLICY "screening_org" ON screening_results
    FOR ALL USING (organization_id = auth_org_id());

-- narratives
CREATE POLICY "narratives_org" ON narratives
    FOR ALL USING (organization_id = auth_org_id());

-- narrative_sections: org_id is denormalized, so this is a simple equality check
CREATE POLICY "sections_org" ON narrative_sections
    FOR ALL USING (organization_id = auth_org_id());

-- section approval: only reviewers and admins may flip approval_status
-- (uses WITH CHECK to restrict the *new* row state, not just which rows are visible)
CREATE POLICY "sections_approve_reviewer" ON narrative_sections
    FOR UPDATE
    USING (organization_id = auth_org_id())
    WITH CHECK (
        -- If approval_status is not changing, any org member can update
        (approval_status = (SELECT ns.approval_status FROM narrative_sections ns WHERE ns.id = id))
        OR
        -- If approval_status IS changing, caller must be reviewer or admin
        EXISTS (
            SELECT 1 FROM users
            WHERE id = auth.uid()
              AND organization_id = auth_org_id()
              AND role IN ('admin', 'reviewer')
        )
    );

-- evidence_links
CREATE POLICY "evidence_links_org" ON evidence_links
    FOR ALL USING (organization_id = auth_org_id());

-- evidence_links are immutable: no UPDATE allowed
CREATE POLICY "evidence_links_no_update" ON evidence_links
    FOR UPDATE USING (false);

-- audit_log: org members can read; only triggers may write (service role only for INSERT)
CREATE POLICY "audit_log_org_read" ON audit_log
    FOR SELECT USING (organization_id = auth_org_id());
