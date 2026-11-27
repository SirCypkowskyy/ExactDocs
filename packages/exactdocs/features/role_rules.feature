Feature: Role rules map provider memberships to ExactDocs roles
  As the admin of an instance shared by a GitHub organization or a company directory
  I want "members of this team get this role" in one place
  So that nobody hands out roles person by person or edits the file at every team change

  Scenario: a team's members get a role on every library
    Given GitHub sign-in admits the organization "acme"
    And the libraries "/acme/docs" and "/acme/api" exist
    And an admin adds the rule "GitHub team acme/docs-writers: contributor on every library"
    When a member of acme/docs-writers signs in
    And the library "/acme/later" is created after the rule
    Then they can edit and re-sync every library, including one created after the rule
    And the Users page shows that this role comes from the rule

  Scenario: an organization's members become viewers
    Given GitHub sign-in admits the organization "acme"
    And the libraries "/acme/docs" and "/acme/api" exist
    And an admin adds the rule "GitHub organization acme: viewer on every library"
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
    And the UI shows these mappings as set by the configuration, read-only

  Scenario: removing a rule takes effect at once
    Given GitHub sign-in admits the organization "acme"
    And the libraries "/acme/docs" and "/acme/api" exist
    And an admin adds the rule "GitHub team acme/docs-writers: contributor on every library"
    And a member of acme/docs-writers is signed in
    When an admin removes the rule "GitHub team acme/docs-writers: contributor on every library"
    Then their next edit of a library they could edit only through that rule is refused
    And the access log names who added and removed the rule

  Scenario: the last admin cannot be removed by a rule change
    Given sign-in provider "corp" of kind "oidc" with issuer "https://idp.example.com"
    And an admin adds the rule "group platform-admins: instance admin"
    And a member of platform-admins signs in
    And the local admin is disabled
    When the admin from platform-admins removes the rule "group platform-admins: instance admin"
    Then the removal is refused with "last_operator"
    And they are still an admin
