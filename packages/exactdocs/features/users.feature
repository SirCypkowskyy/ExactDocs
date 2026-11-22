Feature: Local user accounts
  As an operator of a shared instance
  I want to create, disable and reset local user accounts
  So that team members without OIDC can sign in, and nobody can sign themselves up

  Background:
    Given a fresh instance
    And the admin "ada" was set up with the password "correct horse battery staple"

  Scenario: An operator creates a local user
    When the operator runs "exactdocs user create bob" with the password "bob's long passphrase"
    Then "bob" can sign in with the password "bob's long passphrase"
    And there is no sign-up page

  Scenario: A disabled user is locked out
    Given "bob" is signed in and has an API token
    When the operator disables "bob" in the UI
    Then bob's session and token are refused
    And "bob" cannot sign in with the password "bob's long passphrase"

  Scenario: Resetting a user's password in the UI ends their sessions
    Given "bob" is signed in and has an API token
    When the operator resets the password of "bob" to "bob's brand new passphrase" in the UI
    Then bob's session and token are refused
    And "bob" can sign in with the password "bob's brand new passphrase"

  Scenario: Only an operator manages users
    Given "bob" is signed in and has an API token
    Then bob cannot list, create, disable or reset users: each is forbidden
    And bob's token cannot list users either

  Scenario: The users list sorts, filters and pages on the server
    Given the operator created the users "carol", "bob" and "dave", and disabled "dave"
    When the operator lists the enabled users by name, 2 at a time
    Then the first page shows "ada, bob" and the next one "carol"
    And each page counts 3 users
    And sorting the users by "nickname" is refused, naming the field
