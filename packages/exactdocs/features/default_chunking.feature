Feature: New libraries are chunked at headings 1 to 3 with a 4,000-character bound
  As an operator adding documentation without tuning it
  I want a new library cut at its top three heading levels, and a long chunk cut again
  So that search finds the right section more often, as the retrieval benchmark measured (#381)

  Background:
    Given the fixture repository is a private copy
    And a branch "deep" adds "docs/deep.md" with a "####" heading in a short section and several in a section longer than 4,000 characters

  Scenario: A new library is chunked with the recommended default
    Given an instance with default settings
    When a library is added without chunking settings
    Then its articles start a chunk at headings of level 1 to 3
    And a chunk longer than 4,000 characters is cut again at deeper headings

  Scenario: A library added with its own chunking keeps it
    Given an instance with default settings
    When a library is added with the split level "h6" and no size bound
    Then its chunking settings are the split level "h6" and no size bound
    And every heading of "docs/deep.md" starts a chunk
