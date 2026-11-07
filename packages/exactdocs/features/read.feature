Feature: Reading whole articles and single chunks verbatim
  As an AI coding agent or REST client
  I want the exact stored text of an article or of one chunk, with proof of where it came from
  So that I can quote it, read around a search hit, and learn when my chunk ID is out of date

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: Reading an article
    When an agent reads "docs/guide/install.md" of "/fixture/docs-repo/v1.4.0"
    Then the Markdown arrives after the notice as a plain text block, identical to the imported file
    And the structured content has its front matter, commit SHA and source link
    And the structured content carries the untrusted-content notice

  Scenario: A wrong path suggests close matches
    When an agent reads "docs/guide/instal.md" of "/fixture/docs-repo/v1.4.0"
    Then the tool error lists "docs/guide/install.md" as a close match

  Scenario: A path that exists only in another version is not answered from it
    When an agent reads "docs/guide/setup.md" of "/fixture/docs-repo/v1.4.0"
    Then the tool error code is "not_found"

  Scenario: Reading a neighbor chunk
    Given a search result for "retry_policy" in "/fixture/docs-repo/v1.4.0"
    When the agent reads its next chunk ID
    Then it gets that chunk verbatim with its location and the IDs of its own neighbors

  Scenario: Reading a chunk over REST
    Given a search result for "retry_policy" in "/fixture/docs-repo/v1.4.0"
    When a client reads the chunk of that result over REST
    Then the response status is 200
    And the chunk is that result's text with its commit SHA and source link

  Scenario: A chunk ID nobody ever issued is not found
    When a client reads the chunk "0123456789abcdef0123456789abcdef" over REST
    Then the response status is 404
    And the error code is "not_found"

  Scenario: An outline lists headings only
    When an agent calls "article_outline" for "docs/guide/install.md" of "/fixture/docs-repo/v1.4.0"
    Then it gets the heading tree with chunk IDs and no body text
    And every chunk ID of the outline reads that section of the article

  Scenario: A wrong path in an outline suggests close matches
    When an agent calls "article_outline" for "docs/guide/instal.md" of "/fixture/docs-repo/v1.4.0"
    Then the tool error lists "docs/guide/install.md" as a close match

  Scenario: An outline is not answered from another version
    When an agent calls "article_outline" for "docs/guide/setup.md" of "/fixture/docs-repo/v1.4.0"
    Then the tool error code is "not_found"

  Scenario: Reading an outline over REST
    When a client reads the outline of "docs/guide/install.md" of "/fixture/docs-repo/v1.4.0" over REST
    Then the response status is 200
    And the outline is the heading tree of the article with its commit SHA
