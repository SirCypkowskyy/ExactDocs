@integration @weaviate
Feature: Weaviate holds the search and vector indexes
  As an operator who runs Weaviate (self-hosted or Weaviate Cloud)
  I want ExactDocs' chunks and vectors stored and searched there, filtered to the asked version
  So that keyword, vector and hybrid search run on the vector database I already operate

  The database still keeps every chunk and vector; Weaviate holds a copy per version, with the
  vectors ExactDocs computed (no Weaviate vectorizer). The scenario needs a Weaviate server
  (EXACTDOCS_TEST_WEAVIATE_URL, EXACTDOCS_TEST_WEAVIATE_GRPC_URL when gRPC is not on port 50051,
  and EXACTDOCS_TEST_WEAVIATE_API_KEY when it takes a key): CI runs the pinned
  cr.weaviate.io/semitechnologies/weaviate image. The embedding endpoint is a fake gateway that
  hashes terms.

  Scenario: ExactDocs indexes into and searches Weaviate
    Given ExactDocs is configured with a Weaviate URL and a collection name for both indexes
    When the fixture docs repository is imported into Weaviate at "v1.3.0" and "v1.4.0", and "v1.4.0" is embedded
    Then its chunks are Weaviate objects with library and version properties and ExactDocs' own vectors
    And keyword, vector and hybrid searches answer from Weaviate, filtered to the asked version
