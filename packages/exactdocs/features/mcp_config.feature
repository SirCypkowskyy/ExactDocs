Feature: Ready-to-paste MCP client configuration
  As a user of an ExactDocs instance
  I want "exactdocs config" to print the MCP config for my client
  So that I do not hand-write JSON, and my token does not end up in my terminal by accident

  Background:
    Given a fresh instance
    And the admin "ada" was set up with the password "correct horse battery staple"
    And the instance is served on a loopback port
    And the user is logged in with "exactdocs login"

  Scenario: A working snippet for Claude Code
    When the user runs "exactdocs config --client claude --show-token"
    Then a JSON snippet with the server URL and the token is printed
    And an MCP client configured with it can list libraries

  Scenario: The token stays out of the snippet by default
    When the user runs "exactdocs config --client claude"
    Then the stored token is not in the output
    And the output refers to the EXACTDOCS_TOKEN environment variable

  Scenario: Stdio needs no server and no token
    When the user runs "exactdocs config --client cursor --stdio"
    Then the output starts "exactdocs serve --stdio" through uvx

  Scenario: A snippet with a token created for this client
    When the user runs "exactdocs config --client claude --new-token --username ada --password-stdin" with the admin's password
    Then a JSON snippet with the server URL and a new token is printed
    And an MCP client configured with it can list libraries
    And the new token is not the one the user logged in with
