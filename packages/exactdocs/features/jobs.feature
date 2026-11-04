Feature: Background jobs
  As someone importing a large documentation repository
  I want long tasks to run in the background and show how far they got
  So that a request never blocks and I can tell a slow import from a stuck one

  Background:
    Given ExactDocs is running

  Scenario: Seeing how far a job got
    Given a job over 10 files of "/acme/payments" that has finished 4
    When I request that job
    Then the response status is 200
    And the job is running with 4 of 10 files done

  Scenario: Listing the jobs of a library, newest first
    Given a finished job "job-1" of "/acme/payments"
    And a finished job "job-2" of "/acme/payments"
    And a finished job "job-3" of "/acme/ledger"
    When I list the jobs of the library "/acme/payments"
    Then the response status is 200
    And the jobs are, newest first: "job-2", "job-1"

  Scenario: Asking for a job that does not exist
    When I request the job "no-such-job"
    Then the response status is 404
    And the error code is "not_found"
