Feature: A process that lost its executor slot stops before its jobs are adopted
  As the operator of an instance whose server processes share one database
  I want a process that lost its executor slot to stop running jobs in time
  So that no job runs in two processes at once, even when the process was slow to start

  Scenario: A slot lost during a startup longer than the adoption grace is given up in time
    Given a process claims executor slot 1
    And its slot connection dies while DBOS is still starting
    And the startup takes longer than other processes wait before adopting slot 1's jobs
    When the worker starts
    Then the process stops while it is still starting
    And the process stops before another process may adopt slot 1's jobs

  Scenario: A lost slot is given up within halt_timeout even if a job delays its cancellation
    Given a process holds executor slot 1 and runs a job that takes long to react to cancellation
    When another process takes slot 1
    Then the process stops taking jobs and stops DBOS within halt_timeout of the check that found the slot lost
    And it asks to be stopped within that time
    And no job of slot 1 runs in it after another process may resume or adopt the slot's jobs
