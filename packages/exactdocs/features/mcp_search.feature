Feature: Searching one version over MCP
  As an AI coding agent
  I want search_docs to answer from one exact version and say how it found the results
  So that I can tell "nothing exists" from "not everything was checked"

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: Searching a version with nothing configured
    When an agent calls "search_docs" for "/fixture/docs-repo" version "v1.3.0" and "retry_policy"
    Then the result is explicitly empty for "v1.3.0" with retrieval mode "bm25"

  Scenario: A version that was never imported is not found, not answered from another version
    When an agent calls "search_docs" for "/fixture/docs-repo" version "v1.2.0" and "retry_policy"
    Then the tool error says there is no index for "/fixture/docs-repo@v1.2.0"

  Scenario: Asking for a mode that is not configured
    When an agent calls "search_docs" with mode "hybrid"
    Then the tool error lists the available modes "bm25"

  Scenario: Results carry their location and the notice
    When an agent calls "search_docs" for "/fixture/docs-repo" version "v1.4.0" and "retry_policy"
    Then the search result has the notice and every result has a source link and a commit SHA
