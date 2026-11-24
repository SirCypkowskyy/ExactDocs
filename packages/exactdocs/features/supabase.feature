Feature: ExactDocs runs on Supabase, with BM25 that works without pg_search
  As a team that does not run its own PostgreSQL
  I want ExactDocs on a Supabase database, set up with the grants the README lists
  So that search, jobs and hybrid search work there without pg_search, a superuser or CREATEDB

  # The @supabase scenarios run on the supabase/postgres image (EXACTDOCS_TEST_SUPABASE_URL, its
  # `postgres` role over SSL): each one sets up a role and schemas of its own with
  # deploy/supabase.sql, as an operator would in Supabase's SQL editor.

  @integration @supabase
  Scenario: Search works on Supabase without pg_search
    Given a Supabase database set up with "deploy/supabase.sql"
    And ExactDocs serves from it with "sslmode=require", as a role that cannot create databases
    When the fixture library is imported and an agent searches "v1.4.0" for "retry_policy"
    Then the section defining "retry_policy" ranks first
    And /api/health reports the search engine "postgres_fts"
    And DBOS keeps its tables in the role's schema "dbos" and no database was created
    And every connection ExactDocs and DBOS opened uses SSL

  @integration @supabase
  Scenario: The ranking suite on Supabase
    Given a Supabase database set up with "deploy/supabase.sql"
    When the ranking suite runs on Supabase
    Then every expected query ranks its section first, as on SQLite
    And the health check names the search engine "postgres_fts"

  @integration @supabase
  Scenario: Hybrid search on Supabase
    Given a Supabase database set up with "deploy/supabase.sql"
    And ExactDocs runs on it with "vector" enabled in schema "extensions"
    And the operator chose retrieval mode "hybrid", an embedding model is configured and "v1.4.0" is embedded
    When an agent searches "how do I retry failed calls"
    Then the result says retrieval mode "hybrid"
    And the vectors are a column of type "extensions.vector"

  Scenario: The transaction-mode pooler is refused at start
    When ExactDocs starts on "postgresql://postgres.abcdefghijklmnop:pw-7c1e9b@aws-0-test-0.pooler.supabase.com:6543/postgres"
    Then it refuses to start, naming the session pooler on port 5432 and the direct connection
