@integration @postgres
Feature: A shared instance runs on PostgreSQL with several server processes
  As the operator of a team's ExactDocs instance
  I want its server processes to share one PostgreSQL database
  So that the whole team works on the same libraries, and more than one process can serve them

  Scenario: Two processes share one PostgreSQL database
    Given two ExactDocs processes use the same PostgreSQL database
    When a library is imported through the first
    Then the second serves it, and the import ran exactly once

  Scenario: Failed sign-ins count on every process
    Given two ExactDocs processes use the same PostgreSQL database
    When 5 sign-ins for "admin" fail, each from a different address, alternating between the processes
    Then the next sign-in for "admin", from a new address, is throttled on both processes

  Scenario: Resetting the password lifts the username's throttle on every process
    Given two ExactDocs processes use the same PostgreSQL database
    When 5 sign-ins for "admin" fail, each from a different address, alternating between the processes
    And 2 sign-ins for "root" fail, each from a different address, alternating between the processes
    And the operator runs "exactdocs admin reset-password" for "admin" on that database
    Then the throttle count of "admin" is gone, and the other usernames' and the addresses' counts are unchanged
    And the next sign-in for "admin" with the new password, from a new address, succeeds on both processes

  Scenario: Resetting the password forgets the addresses that signed in with the old one
    Given two ExactDocs processes use the same PostgreSQL database
    And "admin" signed in successfully from 203.0.113.7, so that address is remembered for "admin"
    And sign-ins of other usernames are remembered too
    When 5 sign-ins for "admin" fail, each from a different address, alternating between the processes
    And 2 sign-ins for "root" fail, each from a different address, alternating between the processes
    And the operator runs "exactdocs admin reset-password" for "admin" on that database
    Then no sign-in of "admin" is remembered, and the other usernames' remembered sign-ins are unchanged
    And the throttle count of "admin" is gone, and the other usernames' and the addresses' counts are unchanged
    And a failed sign-in for "admin" from 203.0.113.7 counts against the username "admin" again, on both processes

  Scenario: DBOS needs no second database
    Given the database role may not create databases
    When ExactDocs starts on PostgreSQL
    Then DBOS keeps its tables in schema "dbos" of the same database and jobs run

  @pg_search
  Scenario: The same ranking on both engines
    When the ranking suite runs on ParadeDB
    Then every expected query ranks its section first, as on SQLite
    And the health check names the search engine "pg_search"

  Scenario: Without pg_search, PostgreSQL's full-text search answers
    When the ranking suite runs on PostgreSQL without "pg_search"
    Then every expected query ranks its section first, as on SQLite
    And the health check names the search engine "postgres_fts"
