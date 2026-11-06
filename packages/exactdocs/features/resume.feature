Feature: A killed import resumes where it stopped
  As the operator of an ExactDocs instance
  I want an import that a crash or a deploy interrupted to go on from where it was
  So that a large import never starts over from zero

  Scenario: A killed worker resumes without duplicates
    Given an import of 200 files was killed after 120 files
    When ExactDocs starts again
    Then the import finishes from file 121
    And the version has each article exactly once
