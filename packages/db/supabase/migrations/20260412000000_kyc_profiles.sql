-- =============================================================================
-- KYC Profiles + Account Relationships
-- =============================================================================
-- Step 2 GATHER was improvising KYC from historical alerts — this migration
-- provides real customer-onboarding data for the evidence pipeline.
--
-- kyc_profiles: one row per customer per organization, upserted on
-- (organization_id, customer_id).
--
-- account_relationships: directional edges linking customers by
-- beneficial ownership, shared devices/addresses, counterparty activity, etc.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- kyc_profiles
-- ---------------------------------------------------------------------------

CREATE TABLE kyc_profiles (
    id                          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id             UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    customer_id                 TEXT        NOT NULL,

    -- Identity
    legal_name                  TEXT        NOT NULL,
    date_of_birth               DATE,
    nationality                 TEXT,
    country_of_residence        TEXT,
    tax_id                      TEXT,
    tax_id_country              TEXT,

    -- Contact
    email                       TEXT,
    phone                       TEXT,
    address_line1               TEXT,
    address_line2               TEXT,
    city                        TEXT,
    postal_code                 TEXT,
    country                     TEXT,

    -- Customer classification
    customer_type               TEXT        NOT NULL CHECK (customer_type IN
                                    ('individual', 'business', 'trust', 'other')),
    business_registration_number TEXT,
    business_jurisdiction       TEXT,
    occupation                  TEXT,
    source_of_funds             TEXT,
    source_of_wealth            TEXT,
    pep_status                  TEXT        NOT NULL DEFAULT 'not_screened'
                                    CHECK (pep_status IN
                                        ('not_screened', 'clear', 'pep', 'rca')),

    -- Risk
    risk_rating                 TEXT        NOT NULL DEFAULT 'medium'
                                    CHECK (risk_rating IN
                                        ('low', 'medium', 'high', 'prohibited')),
    risk_rating_reason          TEXT,

    -- Onboarding
    onboarded_at                TIMESTAMPTZ NOT NULL,
    onboarding_source           TEXT,
    last_reviewed_at            TIMESTAMPTZ,

    -- Beneficial ownership (for business customers)
    beneficial_owners           JSONB,

    -- Metadata
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (organization_id, customer_id)
);

CREATE INDEX idx_kyc_profiles_org_customer
    ON kyc_profiles(organization_id, customer_id);

CREATE INDEX idx_kyc_profiles_legal_name
    ON kyc_profiles(organization_id, legal_name);

-- ---------------------------------------------------------------------------
-- account_relationships
-- ---------------------------------------------------------------------------

CREATE TABLE account_relationships (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_customer_id      TEXT        NOT NULL,
    related_customer_id     TEXT        NOT NULL,
    relationship_type       TEXT        NOT NULL CHECK (relationship_type IN
                                ('beneficial_owner', 'authorized_signatory',
                                 'shared_address', 'shared_device', 'shared_email',
                                 'transaction_counterparty', 'corporate_officer',
                                 'other')),
    confidence              NUMERIC     NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    first_observed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_observed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    details                 JSONB,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (organization_id, source_customer_id, related_customer_id, relationship_type)
);

CREATE INDEX idx_account_rel_source
    ON account_relationships(organization_id, source_customer_id);

CREATE INDEX idx_account_rel_related
    ON account_relationships(organization_id, related_customer_id);

-- ---------------------------------------------------------------------------
-- RLS — matches the auth_org_id() pattern from 20260315000000_initial_schema
-- ---------------------------------------------------------------------------

ALTER TABLE kyc_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_relationships ENABLE ROW LEVEL SECURITY;

CREATE POLICY "kyc_profiles_org" ON kyc_profiles
    FOR ALL USING (organization_id = auth_org_id());

CREATE POLICY "account_relationships_org" ON account_relationships
    FOR ALL USING (organization_id = auth_org_id());
