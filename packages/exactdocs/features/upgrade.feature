Feature: Upgrades and re-indexing
  As an operator updating ExactDocs
  I want a new release to migrate my data when it starts, and re-indexing to be one command
  So that updating never means importing everything again

  Scenario: Upgrading keeps the libraries
    Given an instance with libraries created by the previous release
    When the new release starts
    Then the database is migrated and the libraries are served unchanged

  Scenario: Re-indexing while serving
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    When the operator runs "exactdocs reindex"
    Then a new index is built while the old one keeps answering, then swapped
