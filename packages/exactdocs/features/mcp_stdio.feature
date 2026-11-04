Feature: MCP over stdio
  As a developer running ExactDocs and my agent on one machine
  I want the agent to start ExactDocs itself, without a network port or a token
  So that it reads the libraries the server imported

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: stdio MCP reads the same libraries as the running server
    When an agent starts "exactdocs serve --stdio"
    Then "list_libraries" lists "/fixture/docs-repo" without any token

  Scenario: stdio MCP needs an existing database
    When an agent starts "exactdocs serve --stdio" on an empty data directory
    Then it exits with an error on stderr naming the missing database
