Feature: Heading-based chunks
  As an AI coding agent
  I want articles cut at their headings and never inside a code block or table
  So that a search result is a section I can use as it is

  Background:
    Given the fixture docs repository is built and served

  Scenario: A section is addressed by its heading path
    When I chunk "docs/guide/install.md" of version "v1.4.0"
    Then there is a chunk with the heading path "Guide > Install > Docker"
    And that chunk keeps its fenced "bash" block whole

  Scenario: The install table stays in one chunk
    When I chunk "docs/guide/install.md" of version "v1.4.0"
    Then the chunk "Guide > Install" holds the whole platform table

  Scenario: Repeated headings are told apart
    When I chunk "docs/guide/install.md" of version "v1.4.0"
    Then the chunks "Guide > Install > Docker > Troubleshooting" and "Guide > Install > From source > Troubleshooting" have anchors "troubleshooting" and "troubleshooting-1"

  Scenario: A parser change re-chunks
    Given the parser version is bumped
    Then the chunking-config hash differs from before

  Scenario: A code fence with only blanks after its backticks names no language
    Given the article "storage.md" has code fences with only spaces or a tab after the backticks
    When I chunk the article "storage.md"
    Then its only chunk holds every fence and names no code language
