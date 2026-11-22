Feature: API tokens
  As the admin of an instance
  I want revocable tokens for agents, the CLI and scripts
  So that they can use ExactDocs without my password or my browser session

  Background:
    Given a fresh instance
    And the admin "ada" was set up with the password "correct horse battery staple"
    And the admin is signed in to the UI

  Scenario: A token works once created and stops working once revoked
    Given the admin created a token named "laptop"
    Then the token value is shown once
    And an MCP client with that token can list the libraries
    And a REST client with that token can list the libraries
    When the admin revokes "laptop"
    Then the same MCP client is refused
    And the same REST client is refused

  Scenario: An expired token is refused
    Given a token that expired yesterday
    When a REST client uses it
    Then the request is refused as unauthenticated

  Scenario: A token cannot mint tokens
    Given the admin created a token named "laptop"
    Then a client with that token cannot create tokens

  Scenario: Without a valid token MCP over HTTP is closed
    Then an MCP client without a token is refused
    And an MCP client with a made-up token is refused

  Scenario: The token list sorts, filters and counts on the server
    Given the admin created tokens named "laptop", "ci-main" and "ci-nightly"
    When the admin lists the tokens matching "ci", by name from Z to A
    Then the token list shows "ci-nightly, ci-main" and counts 2 tokens
