Feature: Azure AI Search holds the search and vector indexes
  As an operator whose RAG systems run on Azure AI Search
  I want ExactDocs' chunks and vectors indexed and searched there, filtered to the asked version
  So that keyword, vector and hybrid search run on the service I already govern

  The database still keeps every chunk and vector; Azure AI Search holds a copy per version, in
  one index for the words and one per embedding space, searched with BM25, vector and hybrid
  (reciprocal rank fusion) queries. There is no emulator: the service here is the in-process fake
  of its REST API, plugged in as the SDK's transport (the manual azure-search workflow runs the
  contract suites against a real service). The embedding endpoint is a fake gateway.

  Scenario: ExactDocs indexes into and searches Azure AI Search
    Given ExactDocs is configured with an Azure AI Search endpoint and index name
    When "v1.3.0" and "v1.4.0" are imported into Azure AI Search and "v1.4.0" is embedded
    Then the Azure AI Search indexes hold their chunks and vectors with library and version fields
    And search_docs answers from Azure AI Search, filtered to the asked version
