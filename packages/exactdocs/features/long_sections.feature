Feature: A section longer than the chunk size limit is served in parts
  As an AI coding agent
  I want a very long section cut between its blocks into chunks of a bounded size
  So that every chunk I search, read or embed is a size I can use, and no code block is cut

  Background:
    Given ExactDocs imports the fixture docs repository
    And the fixture repository is a private copy
    And a branch "long" adds "docs/long.md" whose section "Long > Reference" is several times the chunk size limit, with a code block longer than the limit

  Scenario: A long section is read part by part
    Given "/fixture/docs-repo/long" is imported
    When a client reads the outline of "docs/long.md" of "/fixture/docs-repo/long" over REST
    Then the outline lists the heading "Long > Reference" once
    And reading that heading's chunk and the next ones of the same heading gives the whole section, in order
    And every part is within the chunk size limit except the one that holds the whole code block
