Feature: Liveness and readiness probes
  As the operator of an orchestrator (Docker, Kubernetes, a load balancer)
  I want to ask ExactDocs whether it is alive and whether it can serve
  So that it is restarted when it hangs and gets no traffic while its database is down

  Scenario: A running instance is up and ready
    Given ExactDocs is running on its own database
    Then "/healthz" reports up and "/readyz" reports ready

  Scenario: Readiness follows the database
    Given ExactDocs is running on its own database
    When the database is unreachable
    Then "/healthz" reports up and "/readyz" reports not ready

  Scenario: The probes need no sign-in, even before the first account exists
    Given a fresh instance
    Then "/healthz" reports up and "/readyz" reports ready

  Scenario: Liveness answers in time while the database is busy
    Given ExactDocs is running on its own database
    And a database statement that takes 3 seconds is running
    When the liveness probe is called
    Then it answers within 1 second
    And it reports the database details as unknown
