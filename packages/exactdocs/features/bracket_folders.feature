Feature: A folder named with brackets is a folder
  As a user importing a repository with folders like "app/[locale]" or "[draft]"
  I want a path setting or a context7.json entry naming such a folder to select or exclude
  everything below it, with or without a trailing slash
  So that the library holds exactly the articles I chose

  Background:
    Given ExactDocs imports the fixture docs repository
    And the fixture repository is a private copy
    And a branch "brackets" adds "app/[locale]/intro.md, app/[locale]/guide/setup.md, app/other.md, docs/[draft]/wip.md"
    And its context7.json has the folders "app/[locale], docs" and the excluded folders "[draft]"

  Scenario Outline: Path settings name a bracketed folder
    When "brackets" is added with the paths "<include>" excluding "<exclude>"
    Then the articles of "brackets" below "<folder>" are "<articles>"

    Examples:
      | include       | exclude       | folder | articles                                           |
      | app/[locale]  |               | app/   | app/[locale]/guide/setup.md, app/[locale]/intro.md |
      | app/[locale]/ |               | app/   | app/[locale]/guide/setup.md, app/[locale]/intro.md |
      | docs/         | docs/[draft]  | docs/[ |                                                    |
      | docs/         | docs/[draft]/ | docs/[ |                                                    |

  Scenario: context7.json names a bracketed folder
    When "brackets" is added without paths
    Then the articles of "brackets" below "app/" are "app/[locale]/guide/setup.md, app/[locale]/intro.md"
    And the articles of "brackets" below "docs/[" are ""
    And "/fixture/docs-repo/brackets" has the article "docs/index.md"
