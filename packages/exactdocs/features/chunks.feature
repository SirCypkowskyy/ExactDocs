Feature: Version-scoped chunk IDs
  As an AI coding agent
  I want a chunk ID to name exactly one chunk of one version
  So that read_chunk is unambiguous and an ID survives a re-sync when its section did not change

  Background:
    Given ExactDocs is running with the demo catalog

  Scenario: An unchanged article keeps its chunk IDs when the branch is re-synced
    Given "/acme/payments" version "main" is indexed as "first" at commit "aaa111":
      | path             | text       |
      | guide/auth.md    | auth       |
      | guide/install.md | install v1 |
    When "/acme/payments" version "main" is indexed as "second" at commit "bbb222":
      | path             | text       |
      | guide/auth.md    | auth       |
      | guide/install.md | install v2 |
    Then every chunk of "guide/auth.md" has the same ID in "first" and "second"
    And no chunk of "guide/install.md" has the same ID in "first" and "second"

  Scenario: The same content in two versions is stored once under different chunk IDs
    Given "/acme/payments" version "v1.3.0" is indexed as "old" at commit "aaa111":
      | path             | text    |
      | guide/install.md | install |
    When "/acme/payments" version "v1.4.0" is indexed as "new" at commit "bbb222":
      | path             | text    |
      | guide/install.md | install |
    Then "new" stored no chunk set of its own
    And no chunk of "guide/install.md" has the same ID in "old" and "new"

  Scenario: Indexing the same manifest twice stores nothing new
    Given "/acme/payments" version "main" is indexed as "first" at commit "aaa111":
      | path             | text    |
      | guide/install.md | install |
    When the manifest "first" is indexed again
    Then nothing new was stored
    And every chunk of "guide/install.md" has the same ID in "first" and "first again"

  Scenario: A chunk can be read only once its manifest is active
    Given "/acme/payments" version "main" is indexed as "first" at commit "aaa111":
      | path             | text    |
      | guide/install.md | install |
    When I read the second chunk of "guide/install.md" in "first" as "/acme/payments" version "main"
    Then the chunk cannot be found
    When the manifest "first" is activated
    And I read the second chunk of "guide/install.md" in "first" as "/acme/payments" version "main"
    Then the chunk says "install two" and its previous chunk is the first one
