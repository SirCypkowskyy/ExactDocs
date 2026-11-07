Feature: Metrics for the operator's Prometheus
  As an operator
  I want Prometheus to scrape ExactDocs' metrics
  So that I monitor it with the same stack as everything else, without leaking what users search

  Scenario: Metrics are exposed when enabled
    Given "EXACTDOCS_METRICS" is on
    And a branch of the fixture repository was imported and then synced
    And a user searched "retry_policy"
    When Prometheus scrapes "/metrics"
    Then it gets request, search, import and sync metrics
    And no metric contains "retry_policy", the library or the caller

  Scenario: Only the allowed hosts can scrape
    Given "EXACTDOCS_METRICS" is on
    When Prometheus scrapes "/metrics" as "rebinding.example"
    Then the scrape is refused

  Scenario: No metrics unless enabled
    Given ExactDocs is running with the demo catalog
    When Prometheus scrapes "/metrics"
    Then there are no metrics to scrape
