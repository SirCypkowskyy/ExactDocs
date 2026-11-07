Feature: A folder named with brackets is a folder
  Documentation repositories often have folders like "app/[locale]" or "[slug]". A path setting
  or a context7.json entry that names such a folder selects or excludes everything below it,
  with or without a trailing slash, like any other folder.

  Background:
    Given a repository with the files "app/[locale]/intro.md, app/[locale]/guide/setup.md, app/other.md, docs/[draft]/wip.md, docs/index.md"

  Scenario Outline: Path settings name a bracketed folder
    When it is imported with the paths "<include>" excluding "<exclude>"
    Then the imported articles are "<articles>"

    Examples:
      | include       | exclude       | articles                                          |
      | app/[locale]  |               | app/[locale]/guide/setup.md, app/[locale]/intro.md |
      | app/[locale]/ |               | app/[locale]/guide/setup.md, app/[locale]/intro.md |
      | docs          | docs/[draft]  | docs/index.md                                     |
      | docs          | docs/[draft]/ | docs/index.md                                     |

  Scenario: context7.json names a bracketed folder
    When it is imported with a context7.json with folders "app/[locale], docs" and excluded folders "[draft]"
    Then the imported articles are "app/[locale]/guide/setup.md, app/[locale]/intro.md, docs/index.md"
