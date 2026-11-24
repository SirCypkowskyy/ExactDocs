Feature: People change their own password
  As a person with a local account
  I want to change my password from my account settings
  So that I do not need an operator when it leaked or a policy says so

  Scenario: a person changes their own password
    Given a fresh instance
    And the admin "ada" was set up with the password "correct horse battery staple"
    And a person signed in with a local account, on a laptop and on a phone
    When they give their current password and a new one in Account settings on the laptop
    Then the new password works for the next sign-in and the old one no longer does
    And their other sessions are signed out, this one stays

  Scenario: the current password is checked
    Given a fresh instance
    And the admin "ada" was set up with the password "correct horse battery staple"
    And a person signed in with a local account, on a laptop and on a phone
    When they give a wrong current password
    Then the change is refused, and repeated failures are throttled like sign-ins
    And their other session is untouched

  Scenario: accounts without a local password
    # The instance has an identity provider (and the admin "ada" with a password).
    Given sign-in provider "corp" of kind "oidc" with issuer "https://idp.example.com"
    And a person who only signs in through an identity provider
    Then Account settings does not offer a password change
