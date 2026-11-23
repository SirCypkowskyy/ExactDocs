@libsql
Feature: libSQL holds the search and vector indexes
  As an operator who runs libSQL (a sqld server, Turso, or one local file)
  I want ExactDocs' full-text and vector indexes in libSQL, with its native vector index
  So that several ExactDocs processes share one SQLite-style index without a vector extension

  ExactDocs' own database stays the source of truth (it is SQLite or PostgreSQL, not libSQL:
  see #358); libSQL holds a copy of each version, in FTS5 and in libSQL's own vector index. The
  server case needs EXACTDOCS_TEST_LIBSQL_URL (CI: the pinned libsql-server image, with a JWT in
  EXACTDOCS_TEST_LIBSQL_AUTH_TOKEN); the file case needs the libsql package. The embedding
  endpoint is a fake gateway that hashes terms.

  Scenario Outline: Searches run on libSQL's FTS5 and its native vector index
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And the libSQL scenario notes what the database's own index finds in "v1.4.0"
    When the operator names a <place> as the libSQL search and vector backend and rebuilds
    And every chunk of "v1.4.0" is embedded into libSQL
    Then libSQL holds each version's chunks in FTS5 and the vectors of "v1.4.0" in its vector index
    And libSQL searches answer as on SQLite, filtered to the asked version

    Examples:
      | place             |
      | libSQL server     |
      | local libSQL file |
