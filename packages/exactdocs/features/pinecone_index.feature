@integration @pinecone
Feature: Pinecone holds the vector index
  As an operator whose team keeps its RAG embeddings in Pinecone
  I want ExactDocs' embeddings there, in a namespace of their own
  So that I run no other vector store, and share an index without mixing data

  The scenario needs a Pinecone index: Pinecone Local's single-index image or a real one
  (EXACTDOCS_TEST_PINECONE_URL, see tests/fixtures/index_backends.py): an integration scenario.

  Scenario: ExactDocs stores and searches vectors in Pinecone
    Given ExactDocs is configured with a Pinecone index and namespace, an embedding model, and the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    When every chunk of "v1.4.0" is embedded into Pinecone
    Then its Pinecone vectors are upserted with library and version metadata
    And vector searches of "v1.4.0" answer from Pinecone, filtered to that version
