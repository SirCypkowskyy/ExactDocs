Feature: Version-pinned documentation search
  As an AI coding agent
  I want search to answer from the exact library version I use
  So that I never get a plausible answer for the wrong version, and can read around every result

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: No results in the selected version, even if another version matches
    When a user searches "/fixture/docs-repo/v1.3.0" for "retry_policy"
    Then the result is explicitly empty for version "v1.3.0"
    And no result from "v1.4.0" is returned

  Scenario: A version that was never imported is not found, not answered from another version
    When a user searches "/fixture/docs-repo/v1.2.0" for "retry_policy"
    Then the response status is 404
    And the error code is "not_found"

  Scenario: A result carries its location
    When a user searches "/fixture/docs-repo/v1.4.0" for "retry_policy"
    Then each result has chunk ID, article path, heading path, position of total, previous and next chunk IDs, commit SHA and a source link to the section anchor
    And the response states retrieval mode "bm25", not reranked, and its coverage

  Scenario: Without a version the default version answers and is named
    When a user searches "/fixture/docs-repo" for "retry_policy"
    Then the response says it searched version "v1.4.0"
    And each result has chunk ID, article path, heading path, position of total, previous and next chunk IDs, commit SHA and a source link to the section anchor

  Scenario: Search with an all-of tag filter
    When a user searches "token" in "/fixture/docs-repo/v1.4.0" with all of tags "api, auth"
    Then every result is tagged "api" and "auth"

  Scenario: Every expected query ranks its section first
    When each query of the expected-queries table is searched in its version
    Then its expected section is the top result
