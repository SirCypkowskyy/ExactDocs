Feature: Private repositories import with an encrypted access token
  As a team with private documentation
  I want to give ExactDocs a token once
  So that it imports the docs without ever showing, logging or sending the token elsewhere

  Background:
    Given the fixture HTTP git server requires a token
    And ExactDocs runs with the secret key "first-secret-key-of-at-least-32-chars"

  Scenario: A private repository imports with a token
    When a user adds it with that token
    Then the library imports
    And the token is never returned by the API

  Scenario: The API says a token-backed library is private, never why
    Given a private library was imported
    Then the library is reported as private

  Scenario: A private repository is refused without the token
    When a user adds it without a token
    Then the request fails with "repository_auth_required"
    And the library "/fixture/docs-repo" does not exist

  Scenario: Losing the secret key keeps the docs
    Given a private library was imported
    When ExactDocs restarts with a different secret key
    Then the library is still readable
    And adding a version to it fails with "credentials_required"

  Scenario: Sending the token again after losing the key brings the library back
    Given a private library was imported
    And ExactDocs restarts with a different secret key
    When a user adds a version with the token again
    Then the version imports

  Scenario: The versions of a private repository are listed with the token
    When a user lists its branches and tags with that token
    Then the tag "v1.3.0" is listed
    And the token is never returned by the API

  Scenario: Listing the versions of a private repository without the token is refused
    When a user lists its branches and tags without a token
    Then the request fails with "repository_auth_required"

  Scenario: Only a signed-in person may list versions with a token
    When an API token client lists its branches and tags with that token
    Then the request is refused as not signed in
