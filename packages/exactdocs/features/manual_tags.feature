Feature: Users tag articles by hand, and manual tags follow renames
  As a user whose topics are not visible in paths or front matter
  I want to tag an article once for every version of its library
  So that the tag stays with the article when git sees it moved

  Background:
    Given ExactDocs imports the fixture docs repository

  Scenario: A manual tag applies to all versions and follows a rename
    Given "/fixture/docs-repo/v1.3.0" is imported
    And the user tagged "docs/guide/setup.md" with "onboarding"
    When the user adds the version "v1.4.0"
    Then "docs/guide/setup.md" in "v1.3.0" is tagged "onboarding"
    And "docs/guide/install.md" in "v1.4.0" is tagged "onboarding"
    And "docs/guide/auth.md" in "v1.4.0" is not tagged "onboarding"

  Scenario: Versions imported before the tag get it too
    Given "/fixture/docs-repo/v1.3.0" is imported
    And the user adds the version "v1.4.0"
    When the user tags "docs/guide/setup.md" with "onboarding"
    Then "docs/guide/setup.md" in "v1.3.0" is tagged "onboarding"
    And "docs/guide/install.md" in "v1.4.0" is tagged "onboarding"
    And "docs/guide/install.md" in "v1.4.0" shows "onboarding" as a manual tag

  Scenario: A tag that came with a rename is removed on the path it was set on
    Given "/fixture/docs-repo/v1.3.0" is imported
    And the user tagged "docs/guide/setup.md" with "onboarding"
    And the user adds the version "v1.4.0"
    Then "docs/guide/install.md" in "v1.4.0" shows "onboarding" as a manual tag set on "docs/guide/setup.md"
    When the user removes the manual tags of "docs/guide/install.md"
    Then "docs/guide/install.md" in "v1.4.0" is tagged "onboarding"
    When the user removes the manual tags of "docs/guide/setup.md"
    Then "docs/guide/install.md" in "v1.4.0" has no manual tags
    And "docs/guide/install.md" in "v1.4.0" is not tagged "onboarding"

  Scenario: Manual tags combine with imported tags in listings and search
    Given "/fixture/docs-repo/v1.3.0" is imported
    When the user tags "docs/guide/setup.md" with "onboarding"
    Then "docs/guide/setup.md" in "v1.3.0" carries exactly the tags "guide, install, onboarding"
    And listing "v1.3.0" by the tag "onboarding" gives only "docs/guide/setup.md"
    And searching "v1.3.0" for "docker" with the tag "onboarding" finds only "docs/guide/setup.md"

  Scenario: Removing manual tags keeps the imported ones
    Given "/fixture/docs-repo/v1.3.0" is imported
    And the user tagged "docs/guide/setup.md" with "onboarding"
    When the user removes the manual tags of "docs/guide/setup.md"
    Then "docs/guide/setup.md" in "v1.3.0" carries exactly the tags "guide, install"
    And "docs/guide/setup.md" in "v1.3.0" has no manual tags
    And searching "v1.3.0" for "docker" with the tag "onboarding" finds nothing

  Scenario: A tag that is no tag is refused
    Given "/fixture/docs-repo/v1.3.0" is imported
    When the user tags "docs/guide/setup.md" with "#!?"
    Then the tag is refused as invalid
