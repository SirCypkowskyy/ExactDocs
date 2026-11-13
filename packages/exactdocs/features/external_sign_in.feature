Feature: Sign-in through an OpenID Connect provider, with its groups
  As a team that already has an identity provider
  I want people to sign in with the identity they have, in the groups they are in
  So that access follows the provider and nobody touches ExactDocs when someone leaves

  Background:
    Given sign-in provider "corp" of kind "oidc" with issuer "https://idp.example.com"

  Scenario: First sign-in through OIDC creates the account
    Given no ExactDocs account is linked to subject "u-123" of that issuer
    When "alice" (subject "u-123", group "payments") signs in through "corp"
    Then an account "alice" with role "user" is created and linked to that issuer and subject
    And she is signed in with the usual session cookie

  Scenario: The same subject always reaches the same account, whatever its email
    Given "alice" signed in through "corp" once as subject "u-123"
    When subject "u-123" signs in again with another email and username
    Then she reaches the same account
    And a different subject with alice's old email gets an account of its own

  Scenario: A local account is never taken over by an external sign-in
    Given a local account "bob" exists
    When subject "u-456" with username "bob" signs in through "corp"
    Then the local account "bob" is unchanged and still signs in with its password
    And the new account is named "bob@corp"

  Scenario: Groups follow the identity provider on every sign-in
    Given the IdP puts "alice" in group "payments"
    When "alice" signs in through OIDC
    Then she is a member of ExactDocs group "payments"
    And when the IdP removes her from it, her next sign-in removes her membership

  Scenario: The admin role follows the admin groups
    Given provider "corp" maps group "exactdocs-admins" to the admin role
    And "alice" signed in as a member of "exactdocs-admins" and is an admin
    When the IdP removes her from "exactdocs-admins"
    Then at her next sign-in or revalidation she is a "user"

  Scenario: Losing the allowed group ends the session and refuses the API tokens
    Given provider "corp" allows only group "docs-readers"
    And "carol" signed in as a member of "docs-readers" and has an API token
    When the IdP removes her from "docs-readers"
    Then after the revalidation interval her session ends and her API token is refused
    And her next sign-in is refused with "not_allowed"

  Scenario: A disabled account stays disabled
    Given an operator disabled the account linked to subject "u-123"
    When subject "u-123" signs in through "corp"
    Then the external sign-in is refused with "account_disabled"
    And no session is created

  Scenario Outline: A forged or replayed callback is refused
    When the callback arrives with <forgery>
    Then the external sign-in is refused with "sign_in_failed"
    And no session is created

    Examples:
      | forgery                                                 |
      | a state that was not issued to this browser             |
      | no browser binding at all                               |
      | a wrong nonce                                           |
      | an ID token not signed by a key of the issuer's JWKS    |
      | an ID token signed with HS256 and the issuer's public key |
      | an unsigned ID token                                    |
      | a code and state that were already used                 |

  Scenario: Without a refresh token the session is short
    Given an OIDC provider that issues no refresh token
    When "erin" signs in through it
    Then her session ends after the revalidation grace period and she signs in again

  Scenario: The local admin keeps working as break-glass
    Given a sign-in provider is configured and cannot be reached
    When the local admin signs in with username and password
    Then the sign-in succeeds
    And a sign-in through the provider is refused with "provider_unavailable"
