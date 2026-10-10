-- SafePay database role bootstrap. Run ONCE per cluster/database as a superuser:
--
--   psql -v ON_ERROR_STOP=1 -U <superuser> -d <dbname> \
--        -v dbname=<dbname> \
--        -v migrator_password=<secret> -v app_password=<secret> \
--        -v system_password=<secret> -v admin_password=<secret> \
--        -f infra/postgres/bootstrap-roles.sql
--
-- Docker Compose runs this automatically on a fresh volume via
-- infra/postgres/initdb/10-safepay-roles.sh. It is idempotent: re-running it
-- resets role attributes and passwords to the values below.
--
-- Roles
--   safepay_migrator  owns the schema, every table, trigger and function.
--                     Used ONLY by `alembic upgrade`. Not a superuser.
--   safepay_app       used by the public API at runtime. Owns nothing, cannot
--                     create objects, gets column-level grants from the
--                     migrations, and moves (simulated) money only as a deal
--                     BUYER/SELLER through SECURITY DEFINER functions.
--   safepay_system    used only by the background worker: SYSTEM transitions
--                     (expiry, auto-release), re-checked for eligibility in SQL.
--   safepay_admin     used only by the separate admin API: ADMIN decisions,
--                     which require the acting user to be in the `admins` table.
-- The public API never holds the system or admin credentials.

\set ON_ERROR_STOP on

SELECT 'CREATE ROLE safepay_migrator'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'safepay_migrator') \gexec
SELECT 'CREATE ROLE safepay_app'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'safepay_app') \gexec
SELECT 'CREATE ROLE safepay_system'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'safepay_system') \gexec
SELECT 'CREATE ROLE safepay_admin'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'safepay_admin') \gexec

ALTER ROLE safepay_migrator WITH
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT
    PASSWORD :'migrator_password';

ALTER ROLE safepay_app WITH
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
    CONNECTION LIMIT 50
    PASSWORD :'app_password';

ALTER ROLE safepay_system WITH
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
    CONNECTION LIMIT 5
    PASSWORD :'system_password';

ALTER ROLE safepay_admin WITH
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
    CONNECTION LIMIT 10
    PASSWORD :'admin_password';

-- Runtime defaults for the application roles (not security controls).
ALTER ROLE safepay_app SET statement_timeout = '15s';
ALTER ROLE safepay_app SET lock_timeout = '5s';
ALTER ROLE safepay_app SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE safepay_system SET statement_timeout = '60s';
ALTER ROLE safepay_admin SET statement_timeout = '15s';
ALTER ROLE safepay_admin SET idle_in_transaction_session_timeout = '30s';

-- No runtime role may be a member of (act as) any other role.
SELECT format('REVOKE %I FROM %I', r.rolname, mem.rolname)
  FROM pg_auth_members m
  JOIN pg_roles r ON r.oid = m.roleid
  JOIN pg_roles mem ON mem.oid = m.member
 WHERE mem.rolname IN ('safepay_app', 'safepay_system', 'safepay_admin') \gexec

-- Database: owned by the migrator, nobody else may connect or create temp objects.
ALTER DATABASE :"dbname" OWNER TO safepay_migrator;
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"dbname" TO safepay_migrator;
GRANT CONNECT ON DATABASE :"dbname" TO safepay_app, safepay_system, safepay_admin;

-- Schema: only the migrator may create objects in it.
ALTER SCHEMA public OWNER TO safepay_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO safepay_app, safepay_system, safepay_admin;

-- Functions created later by the migrator are not executable by PUBLIC by
-- default. This must be the *global* form: PostgreSQL ignores a per-schema
-- (IN SCHEMA) REVOKE of a privilege that is granted globally.
ALTER DEFAULT PRIVILEGES FOR ROLE safepay_migrator REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- Large-object creation is open to PUBLIC by default; the app never needs it,
-- and it would let a leaked app credential fill the disk. (Database-local.)
REVOKE EXECUTE ON FUNCTION
    pg_catalog.lo_create(oid), pg_catalog.lo_creat(integer),
    pg_catalog.lo_from_bytea(oid, bytea)
FROM PUBLIC;
