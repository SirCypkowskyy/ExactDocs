Feature: Role rules map provider memberships to ExactDocs roles
  As the admin of an instance shared by a GitHub organization or a company directory
  I want "members of this team get this role" in one place
  So that nobody hands out roles person by person or edits the file at every team change

  Scenario: an organization's members become viewers
    Given GitHub sign-in admits the organization "acme"
    And the rule "GitHub organization acme: viewer on every library"
    And the libraries "/acme/docs" and "/acme/api" exist
    When an acme member who is in no team signs in
    Then they can read every library and edit none

  Scenario: instance roles from groups
    Given sign-in provider "corp" of kind "oidc" with issuer "https://idp.example.com"
    And the rules "group platform-admins: instance admin" and "group writers: may create libraries"
    When a member of platform-admins signs in
    Then they are an admin
    When they are removed from platform-admins at the identity provider
    Then they are a user again after the next membership check, without signing in again

  Scenario: roles managed at the identity provider
    Given sign-in provider "corp" of kind "oidc" with issuer "https://idp.example.com"
    And its role claim is "roles", configured to map "ExactDocs.Admin" to instance admin and "ExactDocs.Reader" to viewer on every library
    And the libraries "/acme/docs" and "/acme/api" exist
    When someone holding the app role "ExactDocs.Reader" signs in
    Then they are a user with viewer on every library
