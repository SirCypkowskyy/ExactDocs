Feature: A stopping server never waits forever on its nightly upkeep
  As the operator of an instance
  I want the server to stop when I stop it, even when the database fails as it stops
  So that a restart or a deploy never hangs on background work

  Scenario: The upkeep fails while it is cancelled and the server still stops
    Given a server whose nightly upkeep is queueing the embedding
    And the database fails while that queueing is cancelled
    When the server stops
    Then it has stopped without waiting for the next midnight
    And the failure is logged as a warning of the stop

  Scenario: An upkeep that does not stop is left behind after its bound
    Given a server whose nightly upkeep is queueing the embedding
    And that queueing goes on after it is cancelled
    When the server stops
    Then it has stopped within the upkeep's bound
    And a warning says the upkeep did not stop in time
