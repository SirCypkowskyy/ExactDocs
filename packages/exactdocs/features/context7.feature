Feature: A repository's context7.json pre-fills the library
  As a user adding a repository that already describes its docs for context7
  I want ExactDocs to take its title, description, paths and rules
  So that I do not repeat what the project already wrote down

  Background:
    Given ExactDocs imports the fixture docs repository

  Scenario: context7.json pre-fills the selection and rules
    Given the fixture repository has a context7.json with folders "docs" and rules "Use v2 client"
    When a user adds it
    Then title, description and paths are pre-filled and still editable
    And "query-docs" for the library includes the rule "Use v2 client"

  Scenario: Paths a user gives win over context7.json
    When "docs/guide/" of the fixture repository at "next" is imported
    Then the library imports only "docs/guide/"
    And its title is the projectTitle of the context7.json

  Scenario: A version without context7.json keeps the README defaults
    When "docs/" of the fixture repository at "v1.4.0" is imported
    Then the title of the library is the first heading of the README
    And "query-docs" for the library has no rules

  Scenario: The preview offers the previous versions for import
    When a user previews the fixture repository at "next" without paths
    Then the paths of the context7.json are applied
    And "v1.4.0" and "v1.3.0" are offered for import
