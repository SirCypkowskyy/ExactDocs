Feature: Sync failures say which upstream problem it was, and never take the docs away
  As a team that depends on its docs
  I want a sync that meets a deleted repository, an expired credential, a deleted branch or a
  moved tag to keep serving the last good version and tell me which of these it was
  So that I know what to fix upstream while agents keep reading the same docs

  Background:
    Given ExactDocs imports a private copy of the fixture repository over HTTP with a token
    And "/fixture/docs-repo" is imported at "next" and "v1.4.0" with the token

  Scenario Outline: Upstream failures keep serving docs
    Given <problem>
    When the library is synced
    Then the last good version is still served
    And the library shows the error "<code>"

    Examples:
      | problem                           | code             |
      | the repository was deleted        | repo_unreachable |
      | the credential expired            | auth_failed      |
      | branch "next" was deleted         | ref_deleted      |
      | tag "v1.4.0" now points elsewhere | tag_moved        |

  Scenario: A moved tag is reported, never re-imported
    Given tag "v1.4.0" now points elsewhere
    When the library is synced
    Then no import of "v1.4.0" is queued
    And the sync reports "v1.4.0" as failed with "tag_moved"

  Scenario: The same problem is recorded once, and its end is recorded too
    Given the credential expired
    And the library was synced twice
    When the credential is valid again
    And the library is synced
    Then the library has one failed job per version for "auth_failed"
    And the newest job of each version succeeded
