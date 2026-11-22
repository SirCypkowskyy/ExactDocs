Feature: Imports fetch only the chosen ref and paths
  Large repositories must not take minutes or gigabytes to import: one commit, no history,
  and only the files the doc selection can pick.

  Background:
    Given the fixture docs repository is built and served

  Scenario: Only the selected paths of one ref are fetched
    Given the fixture repository has history and files outside "docs/"
    When "docs/" at "v1.4.0" is fetched
    Then the working copy contains "docs/" and the root README only
    And no commit older than "v1.4.0" was fetched

  Scenario: Large files that are not articles never count against the size bound
    Given a repository whose "docs/" folder holds 3 articles and 2000000 bytes of other files
    And ExactDocs fetches at most 400000 bytes
    When "docs/" of that repository is imported
    Then the import succeeds
    And "/fixture/docs-repo/v1.0.0" serves 3 articles

  Scenario: Selected files over the fetch bound fail naming that bound
    Given a repository whose "docs/" folder holds 3 articles of 200000 bytes each
    And ExactDocs fetches at most 400000 bytes
    When "docs/" of that repository is imported
    Then the import fails with "repository_too_large" saying "larger than 400000 bytes"

  Scenario: Selected files over the import bound fail naming that bound
    Given a repository whose "docs/" folder holds 3 articles of 500000 bytes each
    And ExactDocs imports at most 1 MiB of articles
    When "docs/" of that repository is imported
    Then the import fails with "import_too_large" saying "larger than 1 MiB"
