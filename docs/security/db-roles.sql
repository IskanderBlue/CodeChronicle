-- CodeChronicle — least-privilege database roles
-- See tasks/complete/security-hardening-rollout.md, Part A. Run ONCE.
--
-- THE DATABASE IS `codechroniclenet`, NOT `neondb`. The Neon project carries
-- both; `neondb` is the empty default Neon ships and holds none of this
-- product's 104 tables. A grant aimed at `neondb` succeeds and does nothing.
--
-- Connect to the `codechroniclenet` database as `codechroniclenet_app` — the
-- role your current DATABASE_URL uses, which owns the database and all 104
-- tables, and which runs `migrate`. ALTER DEFAULT PRIVILEGES below applies to
-- objects created by the role that RUNS this script, so it MUST be that
-- owner/migrate role — otherwise future migration-created tables won't be
-- granted to cc_app automatically.
--
-- Validated 2026-08-07 on throwaway branch `drill-db-roles-a1`, a copy of
-- prod: both roles come out with the intended privileges, a table created
-- afterwards is granted by the default privileges, and neither role inherits
-- `neon_superuser` (which carries pg_read_all_data + pg_write_all_data and
-- would have made both roles pointless).
--
-- Replace the two placeholder passwords with strong, distinct secrets before
-- running (or run via psql with:  -v app_pw='…' -v ro_pw='…'  and swap the
-- literals below for  :'app_pw'  /  :'ro_pw' ).

-- 1) Runtime application role — CRUD only. No DDL, no role management, no superuser.
--    This is what the live app connects as (goes into the database_url secret).
CREATE ROLE cc_app LOGIN PASSWORD 'REPLACE_WITH_STRONG_APP_PASSWORD';
GRANT CONNECT ON DATABASE codechroniclenet TO cc_app;
GRANT USAGE  ON SCHEMA public    TO cc_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA public TO cc_app;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA public TO cc_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES    TO cc_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT                  ON SEQUENCES TO cc_app;

-- 2) Read-only role — ad-hoc analytics / reporting (never travels with write power).
CREATE ROLE cc_ro LOGIN PASSWORD 'REPLACE_WITH_STRONG_RO_PASSWORD';
GRANT CONNECT ON DATABASE codechroniclenet TO cc_ro;
GRANT USAGE  ON SCHEMA public    TO cc_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cc_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO cc_ro;

-- Verify. One query, and every value is stated, so a wrong one is visible
-- rather than inferred. Expects cc_app = CRUD + sequences, no DDL, no
-- TRUNCATE; cc_ro = SELECT only.
--
--   SELECT 'cc_app' AS role,
--          has_table_privilege('cc_app','users','SELECT')          AS sel,    -- t
--          has_table_privilege('cc_app','users','INSERT')          AS ins,    -- t
--          has_table_privilege('cc_app','users','UPDATE')          AS upd,    -- t
--          has_table_privilege('cc_app','users','DELETE')          AS del,    -- t
--          has_table_privilege('cc_app','users','TRUNCATE')        AS trunc,  -- f
--          has_schema_privilege('cc_app','public','CREATE')        AS ddl,    -- f
--          has_sequence_privilege('cc_app','users_id_seq','USAGE') AS seq     -- t
--   UNION ALL
--   SELECT 'cc_ro',
--          has_table_privilege('cc_ro','users','SELECT'),                     -- t
--          has_table_privilege('cc_ro','users','INSERT'),                     -- f
--          has_table_privilege('cc_ro','users','UPDATE'),                     -- f
--          has_table_privilege('cc_ro','users','DELETE'),                     -- f
--          has_table_privilege('cc_ro','users','TRUNCATE'),                   -- f
--          has_schema_privilege('cc_ro','public','CREATE'),                   -- f
--          has_sequence_privilege('cc_ro','users_id_seq','USAGE');            -- f
--
-- And confirm neither role inherits anything. On Neon this is the check that
-- matters most: a role that comes out a member of `neon_superuser` reads and
-- writes every table whatever the grants above say.
--
--   SELECT r.rolname, r.rolsuper, r.rolcreaterole, r.rolcreatedb,
--          ARRAY(SELECT b.rolname FROM pg_auth_members m
--                JOIN pg_roles b ON m.roleid = b.oid
--                WHERE m.member = r.oid) AS member_of   -- must be {} for both
--   FROM pg_roles r WHERE r.rolname IN ('cc_app','cc_ro');
