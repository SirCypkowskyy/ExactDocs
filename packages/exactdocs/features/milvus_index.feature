@milvus
Feature: Milvus holds the vector index
  As an operator whose vectors already live in Milvus (a server, Zilliz Cloud, or Milvus Lite)
  I want ExactDocs' vectors stored and searched there, filtered to the asked version
  So that vector and hybrid search run on the vector database I already operate

  The database still keeps every vector; Milvus holds a copy per version, in Milvus Lite in a
  temporary directory or, as an integration scenario, on the Milvus server
  EXACTDOCS_TEST_MILVUS_URL names (CI runs the pinned milvusdb/milvus standalone image). The
  embedding endpoint is a fake gateway that hashes terms.

  Scenario Outline: ExactDocs stores and searches vectors in Milvus (<place>)
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And ExactDocs is configured with a Milvus <place> URI and a collection name
    When version "v1.4.0" is embedded into Milvus
    Then its vectors are inserted into Milvus with library and version fields, with a scalar index for filtering
    And vector and hybrid searches answer from Milvus, filtered to the asked version

    Examples: Milvus Lite
      | place |
      | Lite  |

    @integration @milvus_server
    Examples: A server
      | place  |
      | server |
