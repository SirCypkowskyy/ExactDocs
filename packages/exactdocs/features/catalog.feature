Feature: Library catalog
  As an AI coding agent
  I want to address a library and a version by a predictable ID
  So that I always get the version I asked for, never a plausible neighbour

  Background:
    Given ExactDocs is running with the demo catalog

  Scenario: Listing indexed libraries shows each default version
    When I list the libraries over the REST API
    Then the response status is 200
    And the libraries are:
      | id             | versions                   | default version |
      | /acme/ledger   | main                       | main            |
      | /acme/payments | main, next, v1.3.0, v1.4.0 | v1.4.0          |

  Scenario: A library ID without a ref means its default version
    When I request the library "/acme/payments"
    Then the response status is 200
    And the default version of "/acme/payments" is "v1.4.0"

  Scenario: The library ID is not case-sensitive
    When I request the library "/Acme/Payments"
    Then the default version of "/acme/payments" is "v1.4.0"

  Scenario: A ref names exactly that version
    When I request the version "/acme/payments/v1.3.0"
    Then the version used is "v1.3.0" of "/acme/payments"

  Scenario: Refs are case-sensitive and never approximated
    When I request the version "/acme/payments/V1.3.0"
    Then the response status is 404
    And the error code is "not_found"

  Scenario: A malformed ID is rejected
    When I request the library "/acme/pay$ments"
    Then the response status is 422
    And the error code is "validation_error"

  Scenario: Asking for a library that is not indexed
    When I request the library "/vuejs/docs"
    Then the response status is 404
    And the error code is "not_found"
