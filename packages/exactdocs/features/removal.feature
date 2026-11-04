Feature: Removing a version or a library
  As someone who found stale documentation
  I want a removed version or library gone from every surface and from disk
  So that nobody, human or agent, is ever served what I took out

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: A removed version is gone everywhere
    When the user removes version "v1.3.0" of "/fixture/docs-repo"
    Then it does not appear in browse, search, list_libraries or search_docs
    And content used only by "v1.3.0" is garbage-collected
    And content shared with "v1.4.0" is kept

  Scenario: Removing the default version picks the next default
    When the user removes version "v1.4.0" of "/fixture/docs-repo"
    And I request the library "/fixture/docs-repo"
    Then the default version of "/fixture/docs-repo" is "v1.3.0"

  Scenario: Removing the last version leaves the library without versions
    Given the user removed version "v1.3.0" of "/fixture/docs-repo"
    When the user removes version "v1.4.0" of "/fixture/docs-repo"
    Then "/fixture/docs-repo" has no versions
    And searching "/fixture/docs-repo" without a version finds nothing to search

  Scenario: Removing an unknown version
    When the user removes version "v0.1.0" of "/fixture/docs-repo"
    Then the response status is 404
    And the error code is "not_found"

  Scenario: A removed library is gone everywhere
    When the user removes the library "/fixture/docs-repo"
    Then the library "/fixture/docs-repo" does not appear in browse, search, list_libraries or search_docs
    And all content of "/fixture/docs-repo" is garbage-collected
