Feature: Docs from the command line, shaped like ctx7
  As a user of a remote instance
  I want `exactdocs library` and `exactdocs docs` to behave like ctx7's commands
  So that I can check from the terminal what my agent would get

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And the admin created a token named "integration"
    And the instance is served on a loopback port
    And the CLI holds that token

  Scenario: The CLI shows what the agent gets
    When the user runs the command "exactdocs docs /fixture/docs-repo retry policy"
    Then the output equals the text of "query-docs" for the same arguments

  Scenario: A pinned version is asked for with @ or with a slash
    When the user runs the command "exactdocs docs /fixture/docs-repo@v1.4.0 'retry policy'"
    Then the output equals the text of "query-docs" for the same arguments
    When the user runs the command "exactdocs docs /fixture/docs-repo/v1.4.0 'retry policy'"
    Then the output equals the text of "query-docs" for the same arguments

  Scenario: The CLI finds the libraries an agent finds
    When the user runs the command "exactdocs library 'docs repo' 'retry policy'"
    Then the command succeeds
    And the library IDs listed equal the "resolve-library-id" list for "docs repo" and "retry policy"

  Scenario: Scripts get JSON
    When the user runs the command "exactdocs docs /fixture/docs-repo/v1.4.0 'retry policy' --json"
    Then the command succeeds
    And stdout is JSON with the notice and at least one info snippet

  Scenario: Failures use the exit codes and keep stdout empty
    When the user runs the command "exactdocs docs /nobody/nothing 'retry policy'"
    Then the command exits with code 3
    And the output is empty
    When the user runs the command "exactdocs docs fixture 'retry policy'"
    Then the command exits with code 2
    When the user runs the command "exactdocs docs /fixture/docs-repo"
    Then the command exits with code 2
    And the output is empty
