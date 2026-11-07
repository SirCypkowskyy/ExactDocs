Feature: Outlines list every heading of an article
  As an AI coding agent choosing what to read
  I want an article's outline to list every heading, also those its library's chunking merged
  So that I can see everything an article covers before I read one of its chunks

  Background:
    Given ExactDocs imports the fixture docs repository

  Scenario: An outline lists headings merged into one chunk
    Given "/fixture/docs-repo" is imported at "v1.4.0" with min_chars 400
    When an agent calls "article_outline" for "docs/guide/install.md" of "/fixture/docs-repo/v1.4.0"
    Then every heading of the article is in the heading tree
    And a merged heading carries the chunk ID of the chunk that contains it and its own anchor
    And no body text is returned
