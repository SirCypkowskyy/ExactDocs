@postgres
Feature: A warning when PostgreSQL looks like it is behind a transaction-mode pooler
  As the operator of an ExactDocs instance on PostgreSQL
  I want to be told at start when my connection is not a session
  So that a transaction-mode pooler shows up as a clear message, not as jobs failing at random

  # The @pgbouncer scenario needs PgBouncer in transaction mode in front of the test server
  # (EXACTDOCS_TEST_PGBOUNCER_URL, tests/fixtures/databases.py); CI runs one.

  @pgbouncer
  Scenario: A transaction-mode pooler that loses session state is warned about
    Given ExactDocs connects to PostgreSQL through PgBouncer in transaction mode
    And session state does not survive from one transaction to the next
    When ExactDocs starts on that connection
    Then it logs a WARNING that the connection is not a session, naming the session or direct connection to use instead
    And it still starts

  Scenario: A real session is not warned about
    Given ExactDocs connects to PostgreSQL directly
    When ExactDocs starts on that connection
    Then no pooler warning is logged
