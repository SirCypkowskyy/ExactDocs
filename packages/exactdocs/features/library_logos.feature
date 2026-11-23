Feature: A library carries its project's logo, served by ExactDocs
  As a person scanning a long list of libraries
  I want each library to carry its project's logo
  So that I find the one I want at a glance, without the page loading anything from another site

  Background:
    Given ExactDocs imports the fixture docs repository

  Scenario: An imported library carries its project's logo
    When "docs/" of the fixture repository at "next" is imported
    Then the library has a logo
    And the logo is served by ExactDocs as "image/svg+xml"
    And the served logo is the drawing of ".github/logo.svg" at "next" without its script
    And the served logo is a download no script can run in, kept until the logo changes

  Scenario: A library without a logo the importer can use has none
    When "docs/" of the fixture repository at "v1.4.0" is imported
    Then the library has no logo

  Scenario: The logo the README shows wins over the conventional files
    Given the fixture repository is a private copy
    And a branch "branded" whose README opens with the logo "docs/brand/acme-logo.svg"
    When "docs/" of the fixture repository at "branded" is imported
    Then the logo is served by ExactDocs as "image/svg+xml"
    And the served logo is the drawing of "docs/brand/acme-logo.svg" at "branded" without its script

  Scenario: The logo is the default version's
    Given "/fixture/docs-repo/next" is imported
    And the library has a logo
    When "docs/" of the fixture repository at "v1.4.0" is imported
    Then the library has no logo

  Scenario: A re-sync picks up the logo the branch changed
    Given the fixture repository is a private copy
    And "/fixture/docs-repo/next" is imported
    And the library has a logo
    And a commit redrew ".github/logo.svg" on branch "next"
    When the user syncs the library
    Then the library has a new logo
    And the served logo is the drawing of ".github/logo.svg" at "next" without its script
