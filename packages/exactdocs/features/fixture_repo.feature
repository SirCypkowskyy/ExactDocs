Feature: A versioned fixture docs repository
  Import and search are asserted against one stable git repository, served over both transports
  that the importer supports.

  Background:
    Given the fixture docs repository is built and served

  Scenario Outline: Both git servers advertise the same versions
    When I list the remote refs of the fixture repository over <transport>
    Then the remote has the tags "v1.3.0, v1.4.0" and the branch "next"

    Examples:
      | transport |
      | file      |
      | http      |

  Scenario: An identifier exists in one version only
    Then "retry_policy" occurs in version "v1.4.0" but not in version "v1.3.0"
