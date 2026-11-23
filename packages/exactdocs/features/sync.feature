Feature: A branch version re-syncs on demand and re-processes only what changed
  As a documentation maintainer
  I want to pull the latest state of a branch with one action
  So that docs stay fresh without a full re-import, and an upstream problem never takes them away

  Background:
    Given ExactDocs imports the fixture docs repository
    And the fixture repository is a private copy

  Scenario: Nothing to do when the head did not move
    Given "/fixture/docs-repo/next" is imported
    When the user syncs the library
    Then no import runs and the version is reported up to date

  Scenario: Only changed articles are re-chunked
    Given "/fixture/docs-repo/next" is imported
    And a commit changed "docs/guide/install.md" on branch "next"
    When the user syncs the library
    Then only "docs/guide/install.md" is re-chunked and every other article is reused
    And the version keeps its ID with the new commit SHA

  Scenario: Only changed articles are parsed again
    Given "/fixture/docs-repo/next" is imported
    And a commit changed "docs/guide/install.md" on branch "next"
    When the user syncs the library
    Then only "docs/guide/install.md" is parsed and every other article is taken from the catalog
    And every other article reads as it did before the sync

  # Cut at every heading, as before #381. With h1-h3 the held "Guide > Install" chunk also holds
  # its subsections, the commit's new "## Upgrading" becomes a chunk of its own, and the held ID
  # stays valid: nothing would be stale.
  Scenario: A changed section's old chunk ID is stale
    Given "/fixture/docs-repo/next" is imported with a chunk at every heading
    And an agent holds the chunk ID of a section of "docs/guide/install.md"
    And a commit changed "docs/guide/install.md" on branch "next"
    And the user syncs the library
    When the agent reads that chunk ID
    Then it gets the error "stale_chunk"
    And the error names the section's new chunk ID

  Scenario: A tag is never re-synced
    Given "/fixture/docs-repo/v1.3.0" is imported
    When the user syncs the library
    Then no import runs and the version is reported as pinned

  Scenario: A failed sync keeps the last good version
    Given "/fixture/docs-repo/next" is imported
    And the repository is no longer served
    When the user syncs the library
    Then "/fixture/docs-repo/next" is still served at its previous commit
    And the sync job is failed with its reason
