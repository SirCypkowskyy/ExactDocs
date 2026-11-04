Feature: Adding a library with its doc selection
  As an admin
  I want to create a library from a repository, choosing what to import and which ref
  So that every import says exactly which commit it took

  Background:
    Given ExactDocs is running with the demo catalog

  Scenario: Without a ref the default branch is imported
    When a user adds the fixture repository with paths "docs/" and no ref
    Then the library has a version for the default branch
    And that version records the branch head commit SHA
    And an import job is queued for that version

  Scenario Outline: A tag, a branch or a commit is pinned to its commit
    When a user adds the fixture repository with paths "docs/" and the ref "<ref>"
    Then the version is "<ref>" and records the commit of "<commit>"

    Examples:
      | ref    | commit |
      | v1.3.0 | v1.3.0 |
      | next   | next   |

  Scenario: A short commit SHA becomes the full one
    When a user adds the fixture repository with paths "docs/" and the short SHA of "v1.4.0"
    Then the version is the full SHA of "v1.4.0"

  Scenario: An unknown ref creates nothing
    When a user adds the fixture repository with paths "docs/" and the ref "v9.9.9"
    Then the request fails with "unknown_ref"
    And the library "/fixture/docs-repo" does not exist

  Scenario: Exclusions are kept with the library and win over inclusions
    When a user adds the fixture repository with paths "docs/**" and exclusion "docs/archive/**"
    Then the library keeps the inclusion "docs/**" and the exclusion "docs/archive/**"

  Scenario: A pattern that cannot work is refused
    When a user adds the fixture repository with paths "../secrets" and no ref
    Then the request fails with "invalid_path_pattern"

  Scenario: A taken ID asks for another one
    When a user adds the fixture repository as "/acme/payments"
    Then the request fails with "library_id_taken"

  Scenario: The picker lists the tags and branches
    When a user lists the refs of the fixture repository
    Then the default branch is "main", the branches are "main, next" and the tags are "v1.3.0, v1.4.0"
