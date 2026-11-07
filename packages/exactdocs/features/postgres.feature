@postgres
Feature: A shared instance runs on PostgreSQL with several server processes
  As the operator of a team's ExactDocs instance
  I want its server processes to share one PostgreSQL database
  So that the whole team works on the same libraries, and more than one process can serve them

  Scenario: Two processes share one PostgreSQL database
    Given two ExactDocs processes use the same PostgreSQL database
    When a library is imported through the first
    Then the second serves it, and the import ran exactly once

  Scenario: DBOS needs no second database
    Given the database role may not create databases
    When ExactDocs starts on PostgreSQL
    Then DBOS keeps its tables in schema "dbos" of the same database and jobs run
