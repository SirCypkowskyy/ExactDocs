Feature: Version-pinned documentation search
  As an AI coding agent
  I want search to be pinned to the exact library version I use
  So that I never get a plausible answer for the wrong version

  Background:
    Given ExactDocs is running with the demo catalog

  Scenario: The version is a hard filter, not a ranking hint
    When I search "/acme/payments" version "v1.2.0" for "refund"
    Then the response status is 404
    And the error code is "not_found"

  Scenario: An indexed version answers, even with no matching excerpt
    When I search "/acme/payments" version "v1.4.0" for "refund"
    Then the response status is 200
    And I get 0 excerpts
