Feature: A public library whose repository now asks for a login is reported as gone
  As a team that added a public repository without a token
  I want a sync that meets a login prompt to say the repository was deleted or made private
  So that I am not told a credential I never stored was refused

  Scenario: A login prompt without a stored credential is an unreachable repository
    Given ExactDocs imports a public copy of the fixture repository over HTTP
    And "/fixture/docs-repo" is imported at "next" and "v1.4.0" without a token
    And the server now asks for a login, as GitHub does for a deleted repository
    When the library is synced
    Then the last good version is still served
    And the library shows the error "repo_unreachable"
