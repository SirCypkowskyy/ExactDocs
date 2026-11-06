Feature: New tags are imported automatically and branches re-synced on a schedule
  As a documentation maintainer
  I want new releases to become versions without adding each one by hand
  So that the docs follow upstream, while old automatic versions are pruned and mine are kept

  Background:
    Given ExactDocs imports the fixture docs repository and ticks its schedule every second
    And the fixture repository is a private copy
    And "/fixture/docs-repo/next" is imported
    And "v1.3.0" is added by hand
    And tag "v1.4.1" is pushed

  Scenario: A new matching tag becomes a version, old ones are pruned
    Given "/fixture/docs-repo" auto-imports tags "v*" keeping the last 2
    And the scheduled check imported "v1.4.0" and "v1.4.1"
    When tag "v1.5.0" is pushed and the scheduled check runs
    Then "v1.5.0" is imported
    And the oldest auto-imported version is removed
    And manually imported versions are kept

  Scenario: A branch that moved is re-synced by the scheduled check
    Given "/fixture/docs-repo" re-syncs its branches on a schedule
    And a commit changed "docs/guide/install.md" on branch "next"
    When the scheduled check runs
    Then "/fixture/docs-repo/next" serves the new commit
    And no tag was imported
