@chroma
Feature: Chroma holds the vector index
  As an operator whose RAG stack already runs Chroma (a server, Chroma Cloud, or embedded)
  I want ExactDocs' vectors stored and searched there, filtered to the asked version
  So that vector search runs on the vector store I already operate, with ExactDocs' own models

  The database still keeps every vector; Chroma holds a copy per version. With
  EXACTDOCS_TEST_CHROMA_URL the scenario talks to that Chroma server (CI runs the pinned
  chromadb/chroma image); without it, to Chroma's embedded client in a temporary directory. The
  embedding endpoint is a fake gateway that hashes terms: Chroma never embeds anything itself.

  Scenario: ExactDocs stores and searches vectors in Chroma
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And ExactDocs is configured with a Chroma server URL (or a local path) and a collection name
    When version "v1.4.0" is embedded into Chroma
    Then its vectors are added with library and version metadata and ExactDocs' own embeddings
    And vector searches answer from Chroma, filtered to the asked version
