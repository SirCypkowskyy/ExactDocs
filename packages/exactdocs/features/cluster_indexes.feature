Feature: Elasticsearch and OpenSearch hold the search and vector indexes
  As an operator who runs an Elasticsearch or OpenSearch cluster already
  I want ExactDocs to index into it and search it
  So that I use the cluster I run, with each version's chunks kept apart

  The scenario runs against the test cluster named by EXACTDOCS_TEST_ELASTICSEARCH_URL or
  EXACTDOCS_TEST_OPENSEARCH_URL (CI runs both), under an index prefix of its own.

  Scenario Outline: ExactDocs indexes into and searches an <engine> cluster
    Given ExactDocs is configured with a "<engine>" cluster URL and an index prefix
    When versions "v1.3.0" and "v1.4.0" are imported and embedded into the cluster
    Then their chunks are indexed with library and version as keyword fields and their vectors in a "<vector field>" field
    And search_docs answers from the cluster, filtered to the asked version

    @elasticsearch
    Examples: Elasticsearch
      | engine        | vector field |
      | elasticsearch | dense_vector |

    @opensearch
    Examples: OpenSearch
      | engine     | vector field |
      | opensearch | knn_vector   |
