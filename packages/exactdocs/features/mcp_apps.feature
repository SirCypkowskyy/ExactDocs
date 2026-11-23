Feature: MCP Apps render articles and search results as UI
  As a user chatting in a host that supports MCP Apps, such as Claude or ChatGPT
  I want an article or a list of search results shown as UI
  So that reading docs inside the chat is better than reading raw Markdown

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: App tools add UI without changing existing tools
    When a host that supports MCP Apps calls "view_article" for "docs/guide/install.md" of "/fixture/docs-repo/v1.4.0"
    Then it renders the article with headings and code
    And hosts without Apps support get a text fallback
    And "read_article" is unchanged

  Scenario: Search results render with links to their sources
    When a host that supports MCP Apps calls "view_search" for "retry_policy" in "/fixture/docs-repo/v1.4.0"
    Then it renders each result with its heading path and a link to its source
    And hosts without Apps support get the same results as text after the notice

  Scenario: The UI never answers from another version
    When a host that supports MCP Apps calls "view_article" for "docs/guide/setup.md" of "/fixture/docs-repo/v1.4.0"
    Then the tool error code is "not_found"
