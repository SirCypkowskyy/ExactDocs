Feature: Library roles
  As a library owner on a shared instance
  I want roles on each library, enforced in the UI, over REST and over MCP
  So that docs belong to teams, not to whoever imported them

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: A viewer can read but not edit
    Given "bob" is a viewer of "/fixture/docs-repo"
    Then "bob" can search and read it in the UI and over MCP
    But changing its paths is refused

  Scenario: Someone with no role on a library cannot read it
    Given "bob" has no role on "/fixture/docs-repo"
    Then "bob" is refused when searching and reading it in the UI and over MCP

  Scenario: A group's role reaches its members and the highest role wins
    Given "bob" is in the group "corp:docs" that is a contributor of "/fixture/docs-repo"
    And "bob" is a viewer of "/fixture/docs-repo"
    Then "bob" may tag an article of it but not change its paths

  Scenario: A token can select fewer libraries than its user
    Given "bob" is a viewer of "/fixture/docs-repo"
    And "bob" has an agent token limited to "/other/docs"
    Then "bob" cannot discover "/fixture/docs-repo"
    And "bob" sees the same query error for a hidden and a missing library

  Scenario: A library's grants list sorts, filters and pages on the server
    Given "bob" is a viewer of "/fixture/docs-repo"
    And "carol" is a contributor of "/fixture/docs-repo"
    When the operator lists the viewers and contributors of "/fixture/docs-repo" by name from Z to A, 1 at a time
    Then the grant pages show "carol" then "bob", each counting 2 grants
    And "bob" asking for the grants is refused before any page
