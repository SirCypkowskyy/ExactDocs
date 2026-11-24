Feature: Versions carry their article, chunk and embedded-chunk counts
  As an operator looking at a library's versions
  I want each version to say how big it is and how far embedding got
  So that the versions table and the overview need one request, not one per version

  Scenario: Counts on versions
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And chunks were embedded with model "a"
    When the client lists the library's versions
    Then each version carries its article and chunk counts, every chunk embedded
    And the library carries the article count of its default version

  Scenario: A version nothing has embedded yet counts no embedded chunk
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    When the client lists the library's versions
    Then each version carries its article and chunk counts, no chunk embedded
