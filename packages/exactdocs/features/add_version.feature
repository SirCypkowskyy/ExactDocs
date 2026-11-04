Feature: Adding another version to a library
  As a team working on projects pinned to different releases
  I want to add a version next to the ones a library has
  So that every version is imported with exactly the same settings

  Background:
    Given ExactDocs imports the fixture docs repository

  Scenario: A second version uses the library's settings
    Given the fixture repository is imported at "v1.4.0" with paths "docs/**" excluding "docs/archive/**"
    When the user adds the version "v1.3.0"
    Then both "v1.3.0" and "v1.4.0" are listed
    And "/fixture/docs-repo/v1.3.0" has the article "docs/guide/auth.md"
    And "/fixture/docs-repo/v1.3.0" has no article "docs/archive/old-release.md"

  Scenario: The answer points at the import job
    Given "/fixture/docs-repo/v1.4.0" is imported
    When the user adds the version "v1.3.0"
    Then the response says the import was accepted and points to its job

  Scenario: A newer release becomes the default version
    Given "/fixture/docs-repo/v1.3.0" is imported
    When the user adds the version "v1.4.0"
    Then the default version is "v1.4.0"

  Scenario: A branch does not take the default from a release
    Given "/fixture/docs-repo/v1.4.0" is imported
    When the user adds the version "next"
    Then the default version is "v1.4.0"

  Scenario: A version the library already has is refused
    Given "/fixture/docs-repo/v1.4.0" is imported
    When the user adds the version "v1.4.0"
    Then adding the version fails with "version_exists"

  Scenario: An unknown ref queues nothing
    Given "/fixture/docs-repo/v1.4.0" is imported
    When the user adds the version "v9.9.9"
    Then adding the version fails with "unknown_ref"

  Scenario: An unknown library is not found
    When the user adds "v1.3.0" to the library "/nobody/nothing"
    Then the library is not found
