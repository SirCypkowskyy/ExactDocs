Feature: The MCP tools take the arguments agents actually send
  As an AI coding agent, maybe a weaker model
  I want a loosely written tool call to be answered as I meant it, or refused with what to send
  So that an empty string, a large limit or a library's name does not cost me a turn

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: An empty optional argument is treated as not given
    When an agent calls "resolve-library-id" with libraryName "docs-repo" and an empty query
    Then the tool answers as if no query was given

  Scenario: A limit above the maximum is clamped, not refused
    When an agent calls "list_articles" for "/fixture/docs-repo" with limit 1000
    Then the tool returns at most 200 articles and says the limit was capped

  Scenario: search_docs narrows to a path prefix
    When an agent calls "search_docs" for "/fixture/docs-repo" and "token" with path_prefix "docs/api/"
    Then only hits under "docs/api/" are returned

  Scenario: A library named instead of identified
    When an agent calls "search_all_docs" with library "docs-repo" and query "retry_policy"
    Then the results come from "/fixture/docs-repo" and a note says the name was resolved
    When an agent calls "search_docs" with library "docs-repo" and query "retry_policy"
    Then the results come from "/fixture/docs-repo" and a note says the name was resolved

  Scenario: A name that matches several libraries answers with the candidate IDs
    Given the fixture repository is also imported as "/other/docs-repo"
    When an agent calls "search_docs" with library "docs-repo" and query "retry_policy"
    Then the tool error lists the candidate IDs "/fixture/docs-repo" and "/other/docs-repo"

  Scenario: An article that does not exist
    When an agent reads "examples/install_guide_example.md" of "/fixture/docs-repo/v1.4.0"
    Then the tool error lists "docs/guide/install.md" as a close match

  Scenario: An argument the tool does not have is still refused, naming the real ones
    When an agent calls "search_all_docs" with an argument "ref" it does not have
    Then the tool error names the real arguments "query", "library" and "path_prefix"

  Scenario: A version written without its leading v answers from the version written with it
    When an agent calls "search_docs" on "/fixture/docs-repo/1.4.0" for "retry_policy"
    Then version "v1.4.0" answers and a note says ref "1.4.0" was read as it
    When an agent reads "docs/guide/resilience.md" of "/fixture/docs-repo/1.4.0"
    Then version "v1.4.0" answers and a note says ref "1.4.0" was read as it
    When an agent calls "article_outline" for "docs/guide/resilience.md" of "/fixture/docs-repo/1.4.0"
    Then version "v1.4.0" answers and a note says ref "1.4.0" was read as it
    When a user searches "/fixture/docs-repo/1.4.0" for "retry_policy"
    Then the response says it searched version "v1.4.0"

  Scenario: A version the library does not have is refused, naming the versions it has
    When an agent calls "search_docs" on "/fixture/docs-repo/v9.9.9" for "retry_policy"
    Then the tool error names the library's versions "v1.4.0" and "v1.3.0"
    When an agent reads "docs/guide/resilience.md" of "/fixture/docs-repo/v9.9.9"
    Then the tool error names the library's versions "v1.4.0" and "v1.3.0"
    When a user searches "/fixture/docs-repo/v9.9.9" for "retry_policy"
    Then the error response names the library's versions "v1.4.0" and "v1.3.0"
