Feature: Search across libraries
  As an AI coding agent or a user who does not know which library documents something
  I want one search over every library
  So that I see which library answers, and still never get an answer from a non-default version

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And the fixture docs repository is also imported as "/other/guide" at "v1.3.0"

  Scenario: Results across libraries with a library facet
    When a user searches all libraries for "token"
    Then results come from each library's default version
    And each result names its library and version, with counts per library

  Scenario: Selecting a library narrows the results to it
    When a user searches "token" across libraries, narrowed to "/other/guide"
    Then every result comes from "/other/guide" at "v1.3.0"
    And the counts per library still cover both libraries

  Scenario: A non-default version never appears
    When a user searches all libraries for "token"
    Then no result is from version "v1.3.0" of "/fixture/docs-repo"

  Scenario: A library that was never imported is not found
    When a user searches "token" across libraries, narrowed to "/nobody/nothing"
    Then the response status is 404
    And the error code is "not_found"

  Scenario: The tag filter applies to every library
    When a user searches "token" across libraries with all of tags "api, auth"
    Then every result is tagged "api" and "auth"
