Feature: DuckDB holds the search and vector indexes
  As an operator who uses DuckDB for local RAG and analytics
  I want ExactDocs' search and vector indexes in a DuckDB database file
  So that one file holds an index ExactDocs searches and I can query myself

  DuckDB is embedded: the file sits next to ExactDocs, no server. Its full-text extension comes
  with the install (no download), and one process writes the file.

  Scenario: ExactDocs stores and searches chunks in DuckDB
    Given ExactDocs is configured with a DuckDB database file
    When versions "v1.3.0" and "v1.4.0" are imported and embedded into DuckDB
    Then their chunks and vectors are written to DuckDB tables with library and version columns
    And keyword and vector searches answer from DuckDB, filtered to the asked version

  Scenario: A second process does not write the DuckDB file
    Given ExactDocs is configured with a DuckDB database file
    And versions "v1.3.0" and "v1.4.0" are imported and embedded into DuckDB
    When the operator runs "exactdocs index check" while the server runs
    Then the command fails, saying DuckDB lets one process write the file
