Feature: Editing a library's paths or tag rules re-processes every version safely
  As a documentation maintainer whose first selection was not perfect
  I want to change a library's paths and tag rules after adding it
  So that every version follows, while readers keep the old state until the new one is complete

  Background:
    Given ExactDocs imports the fixture docs repository
    And "/fixture/docs-repo" has versions "v1.3.0" and "v1.4.0"

  Scenario: Adding an exclusion re-processes every version
    When the user adds the exclusion "docs/archive/**"
    Then a job re-processes both versions
    And until it finishes, both versions still list "docs/archive/" articles
    And afterwards neither does
    And both versions keep their commits

  Scenario: Changing only a tag rule re-tags every version without fetching
    Given the repository can no longer be fetched
    When the user sets the tag rule "docs/guide/** -> guide-docs"
    Then the re-processing job succeeds without fetching
    And "docs/guide/auth.md" is tagged "guide-docs" in both versions
    And searching both versions with the tag "guide-docs" finds only guide articles
    And "docs/api/auth.md" keeps its front-matter tags in both versions

  Scenario: Invalid settings are refused and nothing is re-processed
    When the user sets the exclusion "../outside"
    Then the settings are refused as invalid
    And no re-processing job is queued

  Scenario: Unchanged settings re-process nothing
    When the user saves the library's settings unchanged
    Then the settings are accepted without a job
