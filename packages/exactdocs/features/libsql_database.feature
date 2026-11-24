@integration @libsql_database
Feature: ExactDocs' own database runs on a libSQL server
  As an operator who runs libSQL (a sqld server, or a Turso database)
  I want ExactDocs' own database on it, as on a SQLite file
  So that several ExactDocs processes share one SQLite-style database

  EXACTDOCS_DATABASE_URL=libsql://host names the server; the libsql-database extra (Turso's
  turso-serverless driver) reaches it over HTTP. The scenario needs a libSQL server of its own,
  EXACTDOCS_TEST_LIBSQL_DATABASE_URL (CI: the pinned libsql-server image, with a JWT in
  EXACTDOCS_TEST_LIBSQL_DATABASE_AUTH_TOKEN), which it empties first.

  Scenario: Two processes share one libSQL database
    Given two ExactDocs processes use the same libSQL server as their database
    When a library is imported through the first
    Then the second serves it from the libSQL server, and the import ran exactly once
    And its searches rank as on a SQLite file
