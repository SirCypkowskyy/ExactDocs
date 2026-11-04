Feature: Starting the server needs git
  As an operator starting ExactDocs with uvx
  I want a clear message when git is missing
  So that I do not discover it later as a failed import

  Scenario: Without git, the HTTP server refuses to start
    Given a machine without "git" on its PATH
    When the user runs "exactdocs serve"
    Then start fails with a message saying that git is required

  Scenario: Without git, MCP over stdio still starts
    Given a machine without "git" on its PATH
    When the user runs "exactdocs serve --stdio" on an empty data directory
    Then start fails only because the database is missing
