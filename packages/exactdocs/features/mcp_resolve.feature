Feature: Resolving a library name over MCP like context7
  As an AI coding agent
  I want resolve-library-id to turn a library name into a library ID
  So that a context7-style prompt works against ExactDocs by changing only the URL

  Background:
    Given the fixture repository is imported as "/acme/payments" at "v1.3.0"
    And the fixture repository is imported as "/acme/payments-sdk" at "v1.4.0"

  Scenario: A library name resolves to its ID
    Given the fixture repository is also imported as "/fixture/docs-repo"
    When an agent calls "resolve-library-id" with libraryName "docs repo" and query "retry policy"
    Then "/fixture/docs-repo" is the first match with its title, description, versions, article and chunk counts

  Scenario: The query changes the order
    Given only "/acme/payments-sdk" documents "retry_policy" in its default version
    When an agent calls "resolve-library-id" with libraryName "payments" and query "retry_policy"
    Then "/acme/payments-sdk" is ranked first
    When the agent calls it with libraryName "payments" and query "invoices"
    Then "/acme/payments" is ranked first

  Scenario: Nothing matches
    When an agent calls "resolve-library-id" with libraryName "kubernetes" and query "pods"
    Then the payload says no library was found

  Scenario: context7-compatible tools keep their payload shape
    When an agent calls "resolve-library-id" with libraryName "payments" and query "retry_policy"
    Then the result has two text blocks: the notice with the version, then the payload
    And the tool has no output schema
