Feature: Search and vector indexes can live in an external backend
  As an operator who runs a search engine or a vector database already
  I want ExactDocs' search and vector indexes to live there, rebuilt from the stored chunks
  So that I use the engine I run, and a backend that loses data loses nothing for good

  The database keeps every chunk and every vector; the backend holds a copy of each version.
  The backend here is the in-memory reference one, shared by every process of a scenario, or
  empty in each new process: a backend that was reset.

  Scenario: An operator moves the vector index to an external backend
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And the operator chose retrieval mode "hybrid" and an embedding model
    And every chunk of "v1.4.0" is embedded
    When the operator configures an external vector backend and runs a rebuild
    Then every active version's embeddings are written to the backend
    And searches use it from then on, with the same results for the same scores

  Scenario: An external index that fell behind is reported and rebuilt
    Given ExactDocs is running with an external search backend and the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And the external index lost version "v1.3.0"
    When the operator asks for a check
    Then the check reports "v1.3.0" missing from the search index
    And a search of "v1.3.0" finds nothing until it is rebuilt
    When the operator rebuilds the external indexes
    Then the check reports nothing missing
    And a search of "v1.3.0" finds its sections again

  Scenario: The command line checks and rebuilds an external index
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    When the operator runs "exactdocs index check" against an external search backend that was reset
    Then the command fails, naming "v1.3.0" and "v1.4.0" as missing
    When the operator runs "exactdocs index rebuild" against that backend
    Then the command reports 2 versions written to the backend
