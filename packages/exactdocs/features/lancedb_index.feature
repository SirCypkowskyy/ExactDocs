@lancedb
Feature: LanceDB holds the search and vector indexes
  As an operator of a single-node ExactDocs
  I want its chunks and vectors stored and searched in LanceDB, filtered to the asked version
  So that vectors live outside the database, in a directory or in object storage

  The database still keeps every chunk and vector; LanceDB holds a copy per version. LanceDB is
  embedded: the scenario gives it a temporary directory (an object-store URI works the same way
  through LanceDB's URI and storage options). The embedding endpoint is a fake gateway that
  hashes terms.

  Scenario: ExactDocs stores and searches chunks in LanceDB
    Given ExactDocs is configured with a LanceDB URI (a local directory)
    When versions "v1.3.0" and "v1.4.0" are imported and embedded into LanceDB
    Then their chunks and vectors are written to LanceDB tables with library and version columns
    And keyword, vector and hybrid searches answer from LanceDB, filtered to the asked version
