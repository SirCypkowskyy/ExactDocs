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
