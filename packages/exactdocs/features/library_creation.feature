Feature: Instance library creation permission
  Operators choose who may create libraries; successful creators own their libraries.

  Scenario: A user outside the permitted group cannot create a library
    Given only group "docs-admins" may create libraries
    When "bob" outside that group adds a library
    Then library creation is refused without storing the library

  Scenario: A permitted group member owns the new library
    Given only group "docs-admins" may create libraries
    And "bob" belongs to library creator group "docs-admins"
    When "bob" adds a permitted library
    Then "bob" owns the new library
