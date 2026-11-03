Feature: Version-pinned documentation search
  As an AI coding agent
  I want search to be pinned to the exact library version I use
  So that I never get a plausible answer for the wrong version

  Background:
    Given ExactDocs is running with the demo catalog

  Scenario: The version is a hard filter, not a ranking hint
    When I search "/reactjs/react.dev" version "18.3" for "useFormState"
    Then the response status is 404
    And the error code is "not_found"

  Scenario: An indexed version answers, even with no matching excerpt
    When I search "/reactjs/react.dev" version "19.1" for "useActionState"
    Then the response status is 200
    And I get 0 excerpts
