-- ============================================================================
-- Vespeiro Public API — Row Level Security Policies
-- ============================================================================
-- This migration enables public read access to key tables via Supabase's
-- auto-generated REST API (PostgREST). All tables use the anon/public key
-- with read-only access. No authentication required.
--
-- Apply via Supabase SQL Editor or: pg < backend/alembic/versions/2026_05_28_rls_public_api.sql
-- ============================================================================

-- ── Enable RLS on all public-facing tables ──────────────────────────────────

ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE people ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;

-- ── Drop any existing policies (idempotent re-run, PG 9.5+ syntax) ──────────

DROP POLICY IF EXISTS "Public read access — sources" ON sources;
DROP POLICY IF EXISTS "Public read access — articles" ON articles;
DROP POLICY IF EXISTS "Public read access — people" ON people;
DROP POLICY IF EXISTS "Public read access — appointments" ON appointments;

-- ── Create public read-only policies ────────────────────────────────────────

-- Sources (active + inactive, full read)
CREATE POLICY "Public read access — sources"
    ON sources
    FOR SELECT
    USING (true);

-- Articles: public read of metadata columns only (content_text excluded)
-- Full text is available only via the service_role key for internal analysis.
-- This respects copyright by not exposing full article text publicly.
CREATE POLICY "Public read access — articles"
    ON articles
    FOR SELECT
    USING (true);

-- Column-level grants: anon role only sees metadata, not full text
GRANT SELECT (id, source_id, external_id, url, title, summary,
              author, published_at, collected_at, language)
    ON articles TO anon, authenticated;

-- People: full read (names are public information from DRE)
CREATE POLICY "Public read access — people"
    ON people
    FOR SELECT
    USING (true);

-- Appointments: full read (public information from Diário da República)
CREATE POLICY "Public read access — appointments"
    ON appointments
    FOR SELECT
    USING (true);

-- ============================================================================
-- API Schema Exposure (PostgREST)
-- ============================================================================
-- After applying, the following endpoints are available:
--
--   GET /rest/v1/sources
--   GET /rest/v1/articles?select=id,source_id,url,title,summary,author,published_at,collected_at,language
--   GET /rest/v1/people
--   GET /rest/v1/appointments
--
-- Filtering examples:
--   /rest/v1/articles?source_id=eq.lusa&order=published_at.desc&limit=100
--   /rest/v1/articles?published_at=gte.2026-05-01&order=published_at.desc
--   /rest/v1/people?select=name,appointments(organization,role,published_at)
--   /rest/v1/appointments?organization=ilike.*RTP*&order=published_at.desc
--
-- Full PostgREST docs: https://postgrest.org/en/stable/references/api.html
-- ============================================================================

-- ── Verify policies ─────────────────────────────────────────────────────────
SELECT
    schemaname,
    tablename,
    policyname,
    cmd AS operation,
    permissive
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('sources', 'articles', 'people', 'appointments')
ORDER BY tablename, policyname;

-- ── Verify column grants ────────────────────────────────────────────────────
SELECT
    table_schema,
    table_name,
    column_name,
    privilege_type
FROM information_schema.column_privileges
WHERE table_schema = 'public'
  AND table_name = 'articles'
  AND grantee = 'anon'
ORDER BY column_name;
