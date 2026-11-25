Feature: Search is hybrid: BM25 and vectors fused with reciprocal rank fusion
  As an AI coding agent
  I want a question in my own words to find the section that uses other words, in the pinned version
  So that "how do I retry failed calls" finds RetryPolicy, and exact identifiers still come first

  Hybrid is chosen by the operator here: it becomes a default only once the eval suite shows it
  beats BM25 (docs/evals/gates.md#becoming-a-default). The embedding endpoint is a fake gateway that hashes terms.

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And the operator chose retrieval mode "hybrid" and an embedding model

  Scenario: Hybrid search when an embedding model is configured
    Given every chunk of "v1.4.0" is embedded
    When an agent searches "how do I retry failed calls"
    Then the result says retrieval mode "hybrid"
    And no chunk from another version is returned

  Scenario: Exact identifiers still come first
    Given every chunk of "v1.4.0" is embedded
    When an agent searches "RetryPolicy"
    Then the section defining "RetryPolicy" ranks first, as in BM25

  Scenario: The embedding provider fails on the query
    Given every chunk of "v1.4.0" is embedded
    And the embedding provider refuses every call
    When an agent searches "how do I retry failed calls"
    Then BM25 answers with fallback reason "embedding_unavailable"
