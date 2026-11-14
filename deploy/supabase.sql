-- ExactDocs on Supabase (docs/deployment.md, "Supabase"): run once in the SQL editor, as `postgres`.
-- A login role of its own, without CREATEDB, owning one schema for ExactDocs' tables and one
-- for DBOS's. Neither schema is exposed by Supabase's Data API unless you add it there.
-- Then give the role a password of your own, in a statement of its own (docs/deployment.md, step 2).
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
CREATE ROLE exactdocs LOGIN NOCREATEDB NOCREATEROLE; -- no password yet: it cannot sign in
GRANT exactdocs TO postgres; -- lets `postgres` hand the schemas to it (PostgreSQL 16 and newer)
CREATE SCHEMA exactdocs AUTHORIZATION exactdocs;
CREATE SCHEMA dbos AUTHORIZATION exactdocs;
GRANT USAGE ON SCHEMA extensions TO exactdocs; -- pgvector's type and operators
ALTER ROLE exactdocs SET search_path = exactdocs, extensions;
