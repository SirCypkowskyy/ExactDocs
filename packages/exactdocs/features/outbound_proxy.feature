Feature: Behind a corporate proxy
  As an operator whose network lets nothing out but a forward proxy
  I want ExactDocs to reach git hosts through it, and to say so when the proxy is the problem
  So that imports work behind the proxy and a failure points at what to fix

  Scenario: A repository only the proxy can reach is previewed through it
    Given ExactDocs runs behind a forward proxy that alone can reach the fixture repository
    When a user previews the repository behind the proxy at "v1.4.0" with paths "docs/**"
    Then the matching files are listed with their count
    And the proxy carried the request to the repository's host

  Scenario: A proxy that wants credentials ExactDocs was not given is named in the error
    Given ExactDocs runs behind a forward proxy that wants credentials it was not given
    When a user previews the repository behind the proxy at "v1.4.0" with paths "docs/**"
    Then the request fails naming the proxy and the repository's host
    And the error shows no proxy credentials

  Scenario: This machine's own servers are never reached through the proxy
    Given ExactDocs runs behind a forward proxy that refuses every host
    When a user previews the fixture repository served on this machine at "v1.4.0" with paths "docs/**"
    Then the matching files are listed with their count
    And the proxy received nothing
