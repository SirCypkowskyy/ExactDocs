Feature: A process that lost its executor slot stops before its jobs are adopted
  As the operator of an instance whose server processes share one database
  I want a process that lost its executor slot to stop running jobs in time
  So that no job runs in two processes at once, even when the process was slow to start

  Scenario: A slot lost during startup is given up in time
    Given a process claims executor slot 1
    And its slot connection dies while DBOS is still starting
    When the watcher starts
    Then the give-up clock counts from the claim
    And the process stops before another process may adopt slot 1's jobs
