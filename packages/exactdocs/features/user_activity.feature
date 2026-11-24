Feature: Operators see when people were last active and every API token
  As an operator of a shared instance
  I want to see when each person was last active, how they sign in and which tokens they hold
  So that I can tidy up the accounts and the tokens nobody uses

  Background:
    Given sign-in provider "google" of kind "oidc" with issuer "https://accounts.google.example"

  Scenario: The users list shows last activity, the sign-in provider and the token count
    Given "alice" signed in through "google" at 09:00 and holds 2 API tokens
    And a local account "bob" exists
    And at 10:40 "alice" used one of her tokens
    When an operator lists the users filtered by provider "google"
    Then only "alice" is listed, signing in through "google", with 2 tokens
    And her last activity shows as 10:00, to the hour
    And filtering by provider "password" lists only the local accounts "ada, bob"

  Scenario: An operator sees every token, never its secret
    Given "alice" signed in through "google" at 09:00 and holds 2 API tokens
    And at 10:40 "alice" used one of her tokens
    When an operator lists all tokens
    Then each token shows its owner "alice", its prefix, its expiry and its last use
    And no token shows its secret or its hash
    And filtering for unused tokens lists only the one she never used
    And "alice" cannot list all tokens: it is forbidden
