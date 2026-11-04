Feature: context7's REST API over the same use cases as the MCP tools
  As an integration that does not speak MCP
  I want context7's library search and docs endpoints
  So that I get the same answers an MCP agent gets, with the same API tokens

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And the admin created a token named "integration"

  Scenario: REST returns the same docs as MCP
    When a client with an API token calls the docs endpoint for "/fixture/docs-repo/v1.4.0" and "retry policy"
    Then the payload equals the "query-docs" payload
    And the response carries the untrusted-content notice

  Scenario: REST finds the same libraries as MCP
    When a client with an API token calls the search endpoint for "docs repo" and "retry policy"
    Then the first result is "/fixture/docs-repo" and the list equals the "resolve-library-id" list

  Scenario: Without a token nothing is served
    When a client without a token calls the docs endpoint for "/fixture/docs-repo/v1.4.0" and "retry policy"
    Then the response status is 401
