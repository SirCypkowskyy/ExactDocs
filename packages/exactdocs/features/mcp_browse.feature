Feature: Browsing documentation over MCP
  As an AI coding agent
  I want to list libraries and page through a version's articles
  So that I find the right article, knowing the text comes from outside and is not an instruction

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: Listing libraries
    When an agent calls "list_libraries"
    Then "/fixture/docs-repo" is listed with title, description and versions with commit SHAs
    And "v1.4.0" is marked as the default version

  Scenario: Paging through a version's articles
    When an agent calls "list_articles" for "/fixture/docs-repo" with limit 2
    Then it gets 2 articles of the default version and a cursor
    When it calls again with that cursor
    Then it gets the next articles

  Scenario: ExactDocs tools carry the notice in structured content
    When an agent calls "list_articles"
    Then its structured result has a "notice" field and the version used

  Scenario: Repository text never replaces the notice
    When an agent calls "list_libraries"
    Then the text the agent reads starts with the notice
