Feature: Querying a library's documentation over MCP like context7
  As an AI coding agent
  I want query-docs to return documentation for a library ID within a size budget
  So that the second call of a context7-style prompt answers from my version and fits my context

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: An exact version answers only from that version
    When an agent calls "query-docs" with libraryId "/fixture/docs-repo/v1.3.0" and query "retry_policy"
    Then no text that exists only in "v1.4.0" is returned

  Scenario: Without a version the default version answers
    When an agent calls "query-docs" with libraryId "/fixture/docs-repo" and query "retry_policy"
    Then the payload contains text that exists only in "v1.4.0"

  Scenario: A version that was never imported is an error, not an answer from another version
    When an agent calls "query-docs" with libraryId "/fixture/docs-repo/v1.2.0" and query "retry_policy"
    Then the call fails with "not_found"

  Scenario: The response stays within the budget
    Given the size budget is 2000 tokens
    When an agent calls "query-docs" with a broad query
    Then the payload is at most 8000 characters
    And the payload holds whole chunks only

  Scenario: The language puts chunks with code in it first
    When an agent calls "query-docs" with libraryId "/fixture/docs-repo/v1.4.0", query "install token retry" and language "python"
    Then the first block has a python code block

  Scenario: The notice comes first and there is no output schema
    When an agent calls "query-docs" with libraryId "/fixture/docs-repo/v1.4.0" and query "retry_policy"
    Then the result has two text blocks: the notice, then the documentation
