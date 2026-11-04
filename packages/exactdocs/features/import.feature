Feature: An import publishes a complete version or nothing
  As an AI coding agent
  I want a version to appear all at once, with the commit it was imported from
  So that I never read half of a version, and a failed import never hides what was served before

  Background:
    Given ExactDocs imports the fixture docs repository

  Scenario: An import publishes the whole version at once
    When "docs/" of the fixture repository at "v1.3.0" is imported
    Then the import succeeds and reports every file as processed
    And "/fixture/docs-repo/v1.3.0" lists every selected article
    And every article and chunk carries the commit SHA of "v1.3.0"

  Scenario: One bad file does not fail the import
    When "docs/" of the fixture repository at "v1.3.0" is imported
    Then the import succeeds
    And the job lists these skipped files:
      | path                        | code        | reason                              |
      | docs/legacy/binary.md       | binary      | binary file                         |
      | docs/legacy/undecodable.md  | undecodable | not text in any supported encoding  |
      | docs/reference/oversized.md | too_large   | larger than 2097152 bytes           |

  Scenario: A Latin-1 file is decoded, not skipped
    When "docs/" of the fixture repository at "v1.3.0" is imported
    Then the article "docs/legacy/latin1.md" of "/fixture/docs-repo/v1.3.0" keeps its accented characters

  Scenario: A failed import leaves the previous state served
    Given "/fixture/docs-repo/next" is imported
    When a re-import of "next" fails before activation
    Then "/fixture/docs-repo/next" still serves the previous commit

  Scenario: Versions stay apart
    Given "/fixture/docs-repo/v1.3.0" is imported
    When "docs/" of the fixture repository at "v1.4.0" is imported
    Then "/fixture/docs-repo/v1.4.0" has the article "docs/guide/resilience.md"
    And "/fixture/docs-repo/v1.3.0" has no article "docs/guide/resilience.md"

  Scenario: Re-importing a commit changes nothing
    Given "/fixture/docs-repo/v1.3.0" is imported
    When "v1.3.0" is imported again
    Then "/fixture/docs-repo/v1.3.0" lists the same articles and chunks as before

  Scenario: Exclusions win over inclusions
    When "docs/**" of the fixture repository at "v1.3.0" is imported excluding "docs/archive/**"
    Then "/fixture/docs-repo/v1.3.0" has no article "docs/archive/old-release.md"
    And "/fixture/docs-repo/v1.3.0" has the article "docs/guide/auth.md"

  Scenario: Front-matter and path-rule tags combine
    When "docs/**" of the fixture repository at "v1.3.0" is imported with the tag rule "docs/api/** -> api"
    Then the article "docs/api/auth.md" of "/fixture/docs-repo/v1.3.0" is tagged "api" and "auth"
