@postgres
Feature: Vectors are stored in pgvector on PostgreSQL
  As the operator of a team's instance on PostgreSQL
  I want hybrid search's vectors kept in the same database, with pgvector
  So that hybrid search needs no separate vector service, and BM25 answers when pgvector is missing

  Scenario: The vector store works on pgvector as on SQLite
    Given ExactDocs runs on PostgreSQL with the "vector" extension available
    And the fixture docs repository is imported at "v1.3.0" and "v1.4.0"
    And embedding space "s1" holds vectors for the chunks of "v1.3.0" and "v1.4.0"
    When the vector index searches "v1.4.0" in "s1" for the 5 nearest chunks to a query vector
    Then it returns at most 5 chunk IDs of "v1.4.0", nearest first, with their cosine distances
    And the vectors of "s1" are a pgvector column of 8 dimensions in the database

  Scenario: A database without pgvector reports why hybrid is off
    Given ExactDocs runs on PostgreSQL without the "vector" extension
    And the fixture docs repository is imported at "v1.3.0" and "v1.4.0"
    And an embedding model is configured
    When an agent searches without a mode
    Then BM25 answers with fallback reason "vector_store_unavailable"
    And /api/health names the missing extension "vector"
