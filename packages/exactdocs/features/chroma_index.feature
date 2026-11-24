@chroma
Feature: Chroma holds the vector index
  As an operator whose RAG stack already runs Chroma (a server, Chroma Cloud, or embedded)
  I want ExactDocs' vectors stored and searched there, filtered to the asked version
  So that vector search runs on the vector store I already operate, with ExactDocs' own models

  The database still keeps every vector; Chroma holds a copy per version, in Chroma's embedded
  client in a temporary directory or, as an integration scenario, on the Chroma server
  EXACTDOCS_TEST_CHROMA_URL names (CI runs the pinned chromadb/chroma image). The embedding
  endpoint is a fake gateway that hashes terms: Chroma never embeds anything itself.

  Scenario Outline: ExactDocs stores and searches vectors in Chroma (<place>)
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And ExactDocs is configured with a Chroma <place> and a collection name
    When version "v1.4.0" is embedded into Chroma
    Then its vectors are added with library and version metadata and ExactDocs' own embeddings
    And vector searches answer from Chroma, filtered to the asked version

    Examples: Embedded
      | place      |
      | local path |

    @integration @chroma_server
    Examples: A server
      | place      |
      | server URL |
