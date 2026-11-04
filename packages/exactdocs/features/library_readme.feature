Feature: A library gets its title and description from the root README
  As an AI coding agent
  I want libraries to carry a meaningful title and description
  So that I can pick the right library in "resolve-library-id" without anyone typing them

  Background:
    Given ExactDocs imports the fixture docs repository

  Scenario: Defaults come from the root README even outside the selection
    When "docs/" of the fixture repository at "v1.3.0" is imported
    Then the title of the library is the first heading of the README
    And the description of the library is the first paragraph of the README

  Scenario: The user can edit them
    Given "/fixture/docs-repo/v1.3.0" is imported
    When the user changes the title to "Payments SDK"
    Then "list_libraries" shows the title "Payments SDK"

  Scenario: An edited title survives a re-import
    Given "/fixture/docs-repo/v1.3.0" is imported
    And the user changes the title to "Payments SDK"
    When "v1.3.0" is imported again
    Then the title of the library is "Payments SDK"
    And the description of the library is the first paragraph of the README
