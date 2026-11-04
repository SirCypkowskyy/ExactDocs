Feature: The CLI is a client of the REST API
  As a user of a remote instance
  I want "exactdocs login" to store my credentials
  So that the CLI commands work without further flags, and without touching the database

  Background:
    Given a fresh instance
    And the admin "ada" was set up with the password "correct horse battery staple"
    And the instance is served on a loopback port

  Scenario: Logging in stores a named token
    When the user runs "exactdocs login" with the admin's username and password
    Then the CLI config holds the server URL and a token
    And the config file is readable by its owner only
    And the stored token is accepted by the server
    And the token list of the admin has a token named after the machine
    And the token is not in the output

  Scenario: A CLI token expires after 90 days unless told otherwise
    When the user runs "exactdocs login" with the admin's username and password
    Then the admin's token expires in 90 days
    When the user runs "exactdocs login" with the admin's username and password and "--expires-in 7"
    Then the admin's newest token expires in 7 days
    When the user runs "exactdocs login" with the admin's username and password and "--no-expiry"
    Then the admin's newest token never expires

  Scenario: An existing token can be read from stdin
    Given the admin is signed in to the UI
    And the admin created a token named "script"
    When the user runs "exactdocs login" with that token on stdin
    Then the CLI config holds the server URL and a token
    And the admin still has exactly 1 token

  Scenario: An existing token can come from the environment
    Given the admin is signed in to the UI
    And the admin created a token named "script"
    When the user runs "exactdocs login" with that token in EXACTDOCS_TOKEN
    Then the CLI config holds the server URL and a token
    And the admin still has exactly 1 token

  Scenario: Logging out forgets the credentials and says the token lives on
    When the user runs "exactdocs login" with the admin's username and password
    And the user runs "exactdocs logout"
    Then no config file exists
    And the output says the token is still valid until revoked

  Scenario: An existing token can be used instead
    Given the admin is signed in to the UI
    And the admin created a token named "script"
    When the user runs "exactdocs login" with that token
    Then the CLI config holds the server URL and a token
    And the admin still has exactly 1 token

  Scenario: A wrong password stores nothing
    When the user runs "exactdocs login" with the password "wrong horse battery staple"
    Then the login is refused with "wrong username or password"
    And no config file exists

  Scenario: Credentials are never sent over plain http to another host
    When the user runs "exactdocs login http://docs.example.com"
    Then the login is refused with "refusing to send credentials over plain http"
