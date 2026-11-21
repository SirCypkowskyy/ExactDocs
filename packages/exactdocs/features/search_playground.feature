Feature: Compare retrieval modes across chosen libraries
  As an operator checking retrieval quality before relying on it
  I want one query run in BM25, vector or hybrid mode over all, one or several libraries
  So that I see which mode finds the right section, with each result's ranks, and why a mode fell back

  The embedding endpoint is a fake gateway that hashes terms: no provider is called.

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And the fixture docs repository is also imported as "/other/guide" at "v1.3.0"

  Scenario Outline: Each mode ranks results across the chosen libraries, with their ranks
    Given the operator chose retrieval mode "bm25" and an embedding model
    And every library is embedded
    When a user searches "how do I retry failed calls" in mode "<mode>" across <libraries>
    Then mode "<mode>" answered without a fallback
    And every result is from a chosen library's default version, with its <ranks>

    Examples:
      | mode   | libraries                                | ranks              |
      | bm25   | all libraries                            | BM25 rank          |
      | vector | all libraries                            | vector rank        |
      | hybrid | all libraries                            | BM25 or vector rank |
      | hybrid | "/fixture/docs-repo" and "/other/guide"  | BM25 or vector rank |
      | vector | "/other/guide"                           | vector rank        |

  Scenario: Vector-only search of one version
    Given the operator chose retrieval mode "bm25" and an embedding model
    And every library is embedded
    When a user searches version "/fixture/docs-repo/v1.4.0" for "how do I retry failed calls" in mode "vector"
    Then mode "vector" answered without a fallback
    And every result is from "v1.4.0"

  Scenario: The embedding provider fails on the query
    Given the operator chose retrieval mode "bm25" and an embedding model
    And every library is embedded
    And the embedding provider refuses every call
    When a user searches "how do I retry failed calls" in mode "hybrid" across all libraries
    Then BM25 answered across the libraries with fallback reason "embedding_unavailable"

  Scenario: Without an embedding model the vector modes are unavailable
    When a user searches "token" in mode "vector" across all libraries
    Then the response status is 422
    And the error code is "mode_unavailable"
