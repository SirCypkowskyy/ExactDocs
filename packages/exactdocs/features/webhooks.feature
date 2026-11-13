Feature: A push to the docs repository triggers a sync
  As a documentation maintainer
  I want my forge to tell ExactDocs when the docs repository changed
  So that teammates and agents read the docs of the last merge, not of the last scheduled check

  Background:
    Given ExactDocs imports the fixture docs repository and never ticks its schedule
    And the fixture repository is a private copy

  Scenario: A signed push to a tracked branch starts a sync
    Given the library "/fixture/docs-repo" has the branch version "main" and a webhook secret
    And "docs/guide/install.md" changed in a new commit on "main"
    When GitHub sends a push for "refs/heads/main" signed with that secret
    Then the answer is 202 within a second
    And a sync of "main" starts within 30 seconds while the library has no other job running

  Scenario: A new tag is imported when auto-import is on
    Given "/fixture/docs-repo" has an auto-sync with tag pattern "v*"
    And tag "v2.1.0" is pushed
    When GitLab sends a tag push for "refs/tags/v2.1.0" with the library's token
    Then the auto-import of "v2.1.0" is queued as "auto"

  Scenario: Bad requests are refused alike
    Given the library "/fixture/docs-repo" has the branch version "main" and a webhook secret
    When a push arrives without a signature, with a wrong signature, or for a library that does not exist
    Then each answer is 401 with the same body
    And no job is queued

  Scenario: A redelivered webhook is ignored
    Given a delivery with ID "d-1" was accepted
    When the same delivery arrives again
    Then the answer is 202 "duplicate" and no second job is queued
