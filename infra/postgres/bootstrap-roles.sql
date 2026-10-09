-- SafePay database role bootstrap. Run ONCE per cluster/database as a superuser:
--
--   psql -v ON_ERROR_STOP=1 -U <superuser> -d <dbname> \
--        -v dbname=<dbname> \
--        -v migrator_password=<secret> -v app_password=<secret> \
--        -f infra/postgres/bootstrap-roles.sql
--
-- Docker Compose runs this automatically on a fresh volume via
-- infra/postgres/initdb/10-safepay-roles.sh. It is idempotent: re-running it
-- resets role attributes and passwords to the values below.
--
-- Roles
--   safepay_migrator  owns the schema, every table, trigger and function.
--                     Used ONLY by `alembic upgrade`. Not a superuser.
--   safepay_app       used by the API at runtime. Owns nothing, cannot create
--                     objects, gets column-level grants from the migrations,
--                     and moves (simulated) money only through SECURITY DEFINER
--                     functions owned by safepay_migrator.

\set ON_ERROR_STOP on

SELECT 'CREATE ROLE safepay_migrator'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'safepay_migrator') \gexec
SELECT 'CREATE ROLE safepay_app'
 WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'safepay_app') \gexec

ALTER ROLE safepay_migrator WITH
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT
    PASSWORD :'migrator_password';

ALTER ROLE safepay_app WITH
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT
    CONNECTION LIMIT 50
    PASSWORD :'app_password';

-- Runtime guard rails for the application role.
ALTER ROLE safepay_app SET statement_timeout = '15s';
ALTER ROLE safepay_app SET lock_timeout = '5s';
ALTER ROLE safepay_app SET idle_in_transaction_session_timeout = '30s';

-- The app role must never be able to become (or act as) the migrator.
SELECT format('REVOKE %I FROM safepay_app', r.rolname)
  FROM pg_auth_members m
  JOIN pg_roles r ON r.oid = m.roleid
 WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = 'safepay_app') \gexec

-- Database: owned by the migrator, nobody else may connect or create temp objects.
ALTER DATABASE :"dbname" OWNER TO safepay_migrator;
REVOKE ALL ON DATABASE :"dbname" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"dbname" TO safepay_migrator;
GRANT CONNECT ON DATABASE :"dbname" TO safepay_app;

-- Schema: only the migrator may create objects in it.
ALTER SCHEMA public OWNER TO safepay_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO safepay_app;

-- Functions created later by the migrator are not executable by PUBLIC by default.
ALTER DEFAULT PRIVILEGES FOR ROLE safepay_migrator IN SCHEMA public
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
