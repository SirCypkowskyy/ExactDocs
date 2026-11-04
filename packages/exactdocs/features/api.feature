Feature: Versioned REST API
  As a developer of the web UI or the CLI
  I want one documented API with stable conventions
  So that every client behaves the same against any instance

  Background:
    Given ExactDocs is running with the demo catalog

  Scenario: The API describes itself
    When I fetch the OpenAPI description
    Then every operation has a stable operation ID and documented error responses

  Scenario: Errors have one shape
    When I request the library "/vuejs/docs"
    Then the response status is 404
    And the error code is "not_found"
    And the error has a message
