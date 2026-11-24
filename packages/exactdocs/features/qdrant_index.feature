@integration @qdrant
Feature: Qdrant holds the vector index
  As an operator who runs Qdrant (self-hosted or Qdrant Cloud)
  I want ExactDocs' vectors stored and searched there, filtered to the asked version
  So that vector and hybrid search run on the vector database I already operate

  The database still keeps every vector; Qdrant holds a copy per version. The scenario needs a
  Qdrant server (EXACTDOCS_TEST_QDRANT_URL, and EXACTDOCS_TEST_QDRANT_API_KEY when it takes a
  key): CI runs the pinned qdrant/qdrant image. The embedding endpoint is a fake gateway that
  hashes terms.

  Scenario: ExactDocs stores and searches vectors in Qdrant
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And ExactDocs is configured with a Qdrant URL and collection name, with native hybrid search
    When every chunk of "v1.4.0" is embedded
    Then its vectors are upserted with library and version payload fields, indexed for filtering
    And vector and hybrid searches answer from Qdrant, filtered to the asked version
