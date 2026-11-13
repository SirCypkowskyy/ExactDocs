Feature: Renames between versions are detected from git
  As a team whose manual tags, version switcher and stale-chunk hints must not lose a moved file
  I want each import to learn which files moved since the previous version
  So that later features can follow an article to its new path

  Background:
    Given ExactDocs imports the fixture docs repository

  Scenario: A renamed article is linked across versions
    Given "/fixture/docs-repo/v1.3.0" is imported
    When the user adds the version "v1.4.0"
    Then the rename map of "v1.4.0" maps "docs/guide/setup.md" to "docs/guide/install.md"

  Scenario: A renamed article can be followed back
    Given "/fixture/docs-repo/v1.3.0" is imported
    When the user adds the version "v1.4.0"
    Then "docs/guide/install.md" of "v1.4.0" came from "docs/guide/setup.md"

  Scenario: An unknown version is not found, unlike a path that was not renamed
    Given "/fixture/docs-repo/v1.3.0" is imported
    Then the rename map of "v9.9.9" is not found

  Scenario: An article that was not renamed has no rename
    Given "/fixture/docs-repo/v1.3.0" is imported
    When the user adds the version "v1.4.0"
    Then the rename map of "v1.4.0" has nothing for "docs/guide/auth.md"

  Scenario: The first version has nothing to compare with
    Given "/fixture/docs-repo/v1.4.0" is imported
    Then the rename map of "v1.4.0" has nothing for "docs/guide/setup.md"

  Scenario: An older version imported later gives the newer one its renames
    Given "/fixture/docs-repo/v1.4.0" is imported
    When the user adds the version "v1.3.0"
    Then the rename map of "v1.4.0" maps "docs/guide/setup.md" to "docs/guide/install.md"
    And "docs/guide/install.md" of "v1.4.0" came from "docs/guide/setup.md"

  Scenario: A version whose renames cannot be detected is still imported
    Given "/fixture/docs-repo/v1.3.0" is imported
    And git cannot compare two commits
    When the user adds the version "v1.4.0"
    Then the import succeeds
    And the rename map of "v1.4.0" has nothing for "docs/guide/setup.md"

  Scenario: A path is followed to a version that skips the one that renamed it
    Given "/acme/payments" has the versions "v1.2.0", "v1.3.0" and "v1.4.0", imported in that order
    And "v1.4.0" renamed "guide/setup.md" of "v1.3.0" to "guide/install.md"
    When I ask where "guide/setup.md" of "v1.2.0" is in "v1.4.0"
    Then the answer is "guide/install.md"

  Scenario: A path is followed back to a version before the one that renamed it
    Given "/acme/payments" has the versions "v1.2.0", "v1.3.0" and "v1.4.0", imported in that order
    And "v1.4.0" renamed "guide/setup.md" of "v1.3.0" to "guide/install.md"
    When I ask where "guide/install.md" of "v1.4.0" is in "v1.2.0"
    Then the answer is "guide/setup.md"

  Scenario: A path that was never renamed did not move across several versions
    Given "/acme/payments" has the versions "v1.2.0", "v1.3.0" and "v1.4.0", imported in that order
    And "v1.4.0" renamed "guide/setup.md" of "v1.3.0" to "guide/install.md"
    When I ask where "guide/auth.md" of "v1.2.0" is in "v1.4.0"
    Then the answer is that it did not move
