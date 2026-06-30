-- Create the FRS and PPE databases + roles on the main Postgres so the AI plugins
-- can share one server instead of running their own postgres containers.
-- Postgres runs every *.sql in /docker-entrypoint-initdb.d ONCE, on first init of a
-- fresh data volume (it is a no-op on an already-initialized volume).
--
-- The FRS/PPE plugins only run `alembic upgrade head` against their DATABASE_URL;
-- they never CREATE the database/role, so this script provides them. Passwords here
-- match the compose defaults (AI_FRS_DB_PASSWORD / AI_PPE_DB_PASSWORD) — override at
-- deploy time and keep these in sync.

-- FRS -----------------------------------------------------------------------
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'frs') THEN
      CREATE ROLE frs LOGIN PASSWORD 'frs';
   END IF;
END
$$;
SELECT 'CREATE DATABASE frs OWNER frs'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'frs')\gexec

-- PPE -----------------------------------------------------------------------
DO $$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ppe') THEN
      CREATE ROLE ppe LOGIN PASSWORD 'ppe';
   END IF;
END
$$;
SELECT 'CREATE DATABASE ppe OWNER ppe'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ppe')\gexec
