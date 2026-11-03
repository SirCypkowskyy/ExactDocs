Feature: Library catalog
  As an AI coding agent
  I want to know which libraries and versions ExactDocs has indexed
  So that I only ask for documentation that actually exists

  Background:
    Given ExactDocs is running with the demo catalog

  Scenario: Listing indexed libraries
    When I list the libraries over the REST API
    Then the response status is 200
    And the libraries are:
      | name               | versions |
      | /fastapi/fastapi   | 0.115    |
      | /reactjs/react.dev | 19.1     |

  Scenario: Asking for a library that is not indexed
    When I request the library "/vuejs/docs"
    Then the response status is 404
    And the error code is "not_found"
