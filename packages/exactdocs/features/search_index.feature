Feature: Full-text search over indexed chunks
  As an AI coding agent
  I want a search to see only the chunks of the version it names
  So that an identifier from a newer release never leaks into an answer for an older one

  Background:
    Given ExactDocs is running with the demo catalog

  Scenario: An identifier introduced in a later version is not found in the earlier one
    Given "/acme/payments" version "v1.3.0" is indexed as "old" at commit "aaa111":
      | path             | text         |
      | guide/retries.md | timeout      |
    And "/acme/payments" version "v1.4.0" is indexed as "new" at commit "bbb222":
      | path             | text         |
      | guide/retries.md | retry_policy |
    When I search the manifest "old" for "retry_policy"
    Then the search finds nothing
    When I search the manifest "new" for "retry_policy"
    Then the first hit highlights "retry_policy"

  Scenario: Search syntax typed by the agent is plain text
    Given "/acme/payments" version "v1.4.0" is indexed as "new" at commit "bbb222":
      | path             | text         |
      | guide/retries.md | retry_policy |
    When I search the manifest "new" for 'NEAR("retry_policy" *'
    Then the first hit highlights "retry_policy"

  Scenario: Content shared by two versions is found from both
    Given "/acme/payments" version "v1.3.0" is indexed as "old" at commit "aaa111":
      | path             | text         |
      | guide/retries.md | retry_policy |
    And "/acme/payments" version "v1.4.0" is indexed as "new" at commit "bbb222":
      | path             | text         |
      | guide/retries.md | retry_policy |
    When I search the manifest "old" for "retry_policy"
    Then the first hit highlights "retry_policy"
    When I search the manifest "new" for "retry_policy"
    Then the first hit highlights "retry_policy"
