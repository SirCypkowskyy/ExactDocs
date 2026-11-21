Feature: OAuth2 and GitHub identities share external sign-in
  Scenario: A generic OAuth2 provider maps its userinfo
    Given a generic OAuth2 provider maps a nested subject and groups
    When Alice completes the generic OAuth2 sign-in
    Then her OAuth2 account is linked to the configured subject and groups

  Scenario: GitHub Enterprise sign-in requires the team
    Given GitHub Enterprise provider "ghe" allows team "acme/docs-readers"
    And the GitHub user has organization access but no allowed team
    When the GitHub user completes external sign-in
    Then GitHub sign-in is refused with code "github_team_required"

  Scenario Outline: GitHub organization setup failures are named
    Given GitHub Enterprise provider "ghe" allows team "acme/docs-readers"
    And the GitHub organization requires <restriction>
    When the GitHub user completes external sign-in
    Then GitHub sign-in is refused with code "<code>"

    Examples:
      | restriction       | code                         |
      | app approval      | github_app_not_approved:acme |
      | SSO authorization | github_sso_required:acme     |

  Scenario: Losing the GitHub team ends the session
    Given GitHub Enterprise provider "ghe" allows team "acme/docs-readers"
    And the GitHub user has an active session and API token
    When the GitHub user loses the allowed team
    Then both the GitHub session and API token are refused

  Scenario: An OAuth2 web MCP host connects while API tokens keep working
    Given a generic OAuth2 provider maps a nested subject and groups
    And MCP OAuth is served through provider "corp2", which allows only group "docs"
    When a web MCP host discovers the OAuth metadata and signs "alice" (group "docs") in
    Then it can call "list_libraries" as that user
    And API tokens keep working

  Scenario: A GitHub MCP host loses access with its team
    Given GitHub Enterprise provider "ghe" allows team "acme/docs-readers"
    And MCP OAuth is served through provider "ghe", which allows only group "github:acme/docs-readers"
    When a web MCP host discovers the OAuth metadata and signs "carol" (group "unused") in
    Then it can call "list_libraries" as that user
    And API tokens keep working
    When the GitHub MCP user loses the allowed team
    Then the token is refused and no tool can be called

  Scenario: A GitHub MCP user without the team cannot connect
    Given GitHub Enterprise provider "ghe" allows team "acme/docs-readers"
    And the GitHub user has organization access but no allowed team
    And MCP OAuth is served through provider "ghe", which allows only group "github:acme/docs-readers"
    When a web MCP host signs "bob" (group "unused") in
    Then the token is refused and no tool can be called
