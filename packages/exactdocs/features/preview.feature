Feature: Previewing an import
  As a user choosing what to import
  I want to see the files my paths would match before importing
  So that a wrong glob is noticed in seconds, not after a long import

  Background:
    Given ExactDocs is running with the demo catalog

  Scenario: A dry run lists files without storing anything
    When a user previews the fixture repository at "v1.4.0" with paths "docs/**"
    Then the matching files are listed with their count
    And no library, version or job exists afterwards

  Scenario: Exclusions win in the preview
    When a user dry-runs "docs/**" excluding "docs/guide/**" at "v1.4.0" of the fixture repository
    Then the matching files are listed with their count
    And none of the listed files is under "docs/guide/"

  Scenario: A ref that does not exist is explained
    When a user previews the fixture repository at "v9.9.9" with paths "docs/**"
    Then the request fails with "unknown_ref"
