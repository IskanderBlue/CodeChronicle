-- CodeChronicle — least-privilege database roles
-- See tasks/security-hardening-rollout.md, Part A. Run ONCE.
--
-- Connect to the `neondb` database as the project OWNER role (the role your
-- current DATABASE_URL uses — i.e. the role that runs `migrate` and creates
-- tables). ALTER DEFAULT PRIVILEGES below applies to objects created by the
-- role that RUNS this script, so it MUST be that owner/migrate role — otherwise
-- future migration-created tables won't be granted to cc_app automatically.
--
-- Replace the two placeholder passwords with strong, distinct secrets before
-- running (or run via psql with:  -v app_pw='…' -v ro_pw='…'  and swap the
-- literals below for  :'app_pw'  /  :'ro_pw' ).

-- 1) Runtime application role — CRUD only. No DDL, no role management, no superuser.
--    This is what the live app connects as (goes into the database_url secret).
CREATE ROLE cc_app LOGIN PASSWORD 'REPLACE_WITH_STRONG_APP_PASSWORD';
GRANT CONNECT ON DATABASE neondb TO cc_app;
GRANT USAGE  ON SCHEMA public    TO cc_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO cc_app;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA public TO cc_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO cc_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT                  ON SEQUENCES TO cc_app;

-- 2) Read-only role — ad-hoc analytics / reporting (never travels with write power).
CREATE ROLE cc_ro LOGIN PASSWORD 'REPLACE_WITH_STRONG_RO_PASSWORD';
GRANT CONNECT ON DATABASE neondb TO cc_ro;
GRANT USAGE  ON SCHEMA public    TO cc_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cc_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cc_ro;

-- Verify (expects cc_app = CRUD/no-DDL, cc_ro = SELECT-only):
--   \du                                  -- list roles; neither should be Superuser/Create role/Create DB
--   SELECT has_table_privilege('cc_app','users','INSERT');   -- t
--   SELECT has_table_privilege('cc_app','users','TRUNCATE'); -- f
--   SELECT has_table_privilege('cc_ro','users','SELECT');    -- t
--   SELECT has_table_privilege('cc_ro','users','UPDATE');    -- f
