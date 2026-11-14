Feature: Vectors are stored per embedding space behind one port, in SQLite with sqlite-vec
  As an operator of hybrid search
  I want chunk vectors kept per embedding model, in the one SQLite file, and searched per version
  So that two models are never mixed, a model change never half-breaks search, and BM25 always answers

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: Nearest chunks come only from the active manifest of the version
    Given embedding space "s1" holds vectors for the chunks of "v1.3.0" and "v1.4.0"
    When the vector index searches "v1.4.0" in "s1" for the 5 nearest chunks to a query vector
    Then it returns at most 5 chunk IDs of "v1.4.0", nearest first, with their cosine distances

  Scenario: A new model gets its own space
    Given space "s1" was built with model "a" at 384 dimensions
    When the operator switches the embedding model to "b" at 1024 dimensions
    Then a new space "s2" is created for "b"
    And vectors of "s1" are never compared with vectors of "s2"

  Scenario: Without sqlite-vec, hybrid is unavailable and BM25 keeps answering
    Given an embedding model is configured, the instance mode is "hybrid" and sqlite-vec cannot load
    When an agent searches without a mode
    Then BM25 answers with fallback reason "vector_store_unavailable"
