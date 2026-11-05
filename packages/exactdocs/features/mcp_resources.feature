Feature: Articles as MCP resources
  As an MCP client that browses resources instead of calling tools
  I want to list and read a version's articles as resources
  So that I get the same Markdown as read_article, still marked as untrusted external text

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: Reading an article as a resource
    When a client reads the first article of "/fixture/docs-repo" at "v1.4.0" as a resource
    Then it gets the same Markdown as "read_article"
    And the notice is the first thing it reads

  Scenario: No ref means the default version
    When a client reads the first article of "/fixture/docs-repo" as a resource without a ref
    Then it gets the same Markdown as "read_article" at "v1.4.0"

  Scenario: Listed resources name their version and page
    When a client lists the resources
    Then every listed resource carries a "ref" and is one page of at most 50
    And reading a listed resource gives the notice first

  Scenario: A path cannot climb out of the article tree
    When a client reads a resource whose path climbs out with ".."
    Then the read fails and no article is returned

  Scenario: stdio serves the same read-only resources
    When an agent starts "exactdocs serve --stdio" and lists resources
    Then the article template is listed without any token
