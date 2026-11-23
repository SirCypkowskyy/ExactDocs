Feature: Azure AI Search holds the search and vector indexes
  As an operator whose RAG systems run on Azure AI Search
  I want ExactDocs' chunks and vectors indexed and searched there, filtered to the asked version
  So that keyword, vector and hybrid search run on the service I already govern

  The database still keeps every chunk and vector; Azure AI Search holds a copy per version, in
  one index for the words and one per embedding space, searched with BM25, vector and hybrid
  (reciprocal rank fusion) queries. There is no emulator: the service here is the in-process fake
  of its REST API, plugged in as the SDK's transport (the manual azure-search workflow runs the
  contract suites against a real service). The embedding endpoint is a fake gateway.

  With a semantic configuration, a hybrid search that asks for reranking (a reranker is
  configured) is reranked by Azure's semantic ranker in the same request; the fake's ranker is a
  deterministic stand-in scoring the share of the query's words each chunk holds. The reranker
  endpoint is the fake gateway too, which reverses the order it is sent.

  Scenario: ExactDocs indexes into and searches Azure AI Search
    Given ExactDocs is configured with an Azure AI Search endpoint and index name
    When "v1.3.0" and "v1.4.0" are imported into Azure AI Search and "v1.4.0" is embedded
    Then the Azure AI Search indexes hold their chunks and vectors with library and version fields
    And search_docs answers from Azure AI Search, filtered to the asked version

  Scenario: Azure's semantic ranker answers a reranked hybrid search
    Given the vector backend is Azure AI Search with a semantic configuration
    And the search on Azure AI Search asks for reranking
    When an agent searches a version on Azure AI Search in hybrid mode
    Then Azure's semantic ranker orders the results, filtered to that version
    And the result says it was reranked by Azure

  Scenario: Without a semantic configuration ExactDocs reranks Azure's hybrid results
    Given the Azure AI Search index has no semantic configuration
    When a reranked search runs on Azure AI Search
    Then ExactDocs' own reranker reranks Azure's results, or none does, as today
