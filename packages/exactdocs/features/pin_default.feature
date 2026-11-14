Feature: Library owners pin the default version
  As a library owner
  I want to pin the default version
  So that my team gets the version it uses, not the newest tag

  Background:
    Given ExactDocs imports the fixture docs repository
    And the fixture repository is a private copy
    And "/fixture/docs-repo/v1.3.0" is imported

  Scenario: A pinned default stays when a higher tag arrives
    Given the default of "/fixture/docs-repo" is pinned to "v1.3.0"
    When "v1.5.0" is imported
    Then "/fixture/docs-repo" still answers with "v1.3.0"
    And list_libraries shows the default as pinned

  Scenario: Unpinned, the default follows the default-version rule again
    Given the default of "/fixture/docs-repo" is pinned to "v1.3.0"
    When "v1.5.0" is imported
    And the user unpins the default of "/fixture/docs-repo"
    Then "/fixture/docs-repo" answers with "v1.5.0"
    And list_libraries shows the default as not pinned

  Scenario: Only an imported version can be pinned
    When the user pins the default of "/fixture/docs-repo" to "v1.4.0"
    Then the response status is 404
    And the error code is "not_found"
