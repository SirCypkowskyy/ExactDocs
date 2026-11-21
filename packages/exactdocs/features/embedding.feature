Feature: An embedding endpoint embeds every version in the background
  As an operator of hybrid search
  I want every version embedded in the background with the model I configure
  So that two models are never mixed, BM25 answers meanwhile, and I know the cost before it starts

  Scenario: Changing the model re-embeds instead of mixing vectors
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And chunks were embedded with model "a"
    When the operator switches to model "b"
    Then all chunks are re-embedded with "b" in the background while BM25 answers
    And until a version is covered by "b", its searches answer "bm25" with fallback reason "embedding_in_progress"

  Scenario: A library that opted out is never sent
    Given library "/acme/secret-docs" has AI "off"
    When the embedding jobs run
    Then no chunk of "/acme/secret-docs" is sent to the embedding provider

  Scenario: The operator sees what embedding every version will cost before it starts
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And an embedding model is configured and nothing is embedded yet
    When the operator runs "exactdocs ai estimate"
    Then it prints the chunks, the estimated tokens and the estimated USD, labelled as an estimate
    And nothing is sent to the embedding provider

  Scenario: A finished embedding reports every chunk of its version done, shared ones included
    Given the fixture repository is a private copy
    And a commit on branch "next" adds one new article as "docs/guide/faq.md" and "docs/faq.md"
    And ExactDocs is running with the fixture docs repository imported at "v1.4.0" and "next"
    And library "/acme/same-docs" holds the same files at "next"
    When the embedding jobs of every library run
    Then every embedding job succeeded with as many chunks done as its total
