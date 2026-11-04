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

  Scenario: An article that was not renamed has no rename
    Given "/fixture/docs-repo/v1.3.0" is imported
    When the user adds the version "v1.4.0"
    Then the rename map of "v1.4.0" has nothing for "docs/guide/auth.md"

  Scenario: The first version has nothing to compare with
    Given "/fixture/docs-repo/v1.4.0" is imported
    Then the rename map of "v1.4.0" has nothing for "docs/guide/setup.md"

  Scenario: A version whose renames cannot be detected is still imported
    Given "/fixture/docs-repo/v1.3.0" is imported
    And git cannot compare two commits
    When the user adds the version "v1.4.0"
    Then the import succeeds
    And the rename map of "v1.4.0" has nothing for "docs/guide/setup.md"
