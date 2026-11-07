Feature: Traces in the operator's own collector
  As an operator
  I want ExactDocs to send its traces to the OpenTelemetry collector I run
  So that I monitor it with the same stack as everything else, without leaking what users search

  Scenario: Traces go only to the configured collector, without query text
    Given telemetry is "otlp" with a local collector
    When a user searches "retry_policy"
    Then the collector receives request and search spans
    And no span contains "retry_policy"
