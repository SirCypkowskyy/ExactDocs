Feature: The retrieval benchmark measures Context7 on the golden set
  As a maintainer comparing ExactDocs with the documentation MCP most coding agents use
  I want to know which pinned versions Context7 serves, and how good its answers are for those
  So that a comparison never mixes the pinned versions with what Context7 serves instead

  Background:
    Given a golden corpus with an answerable and an unanswerable question

  Scenario: Context7's coverage of the pinned versions is reported
    Given a stand-in for Context7 that serves another release in place of the pinned version
    When the run resolves each pinned version in Context7 and asks its questions
    Then the report states that Context7 serves the version unverified
    And the coverage names the library ID Context7 resolved, the release it served and the date

  Scenario: Context7 answers the golden set
    Given a stand-in for Context7 that serves the pinned version
    When the run resolves each pinned version in Context7 and asks its questions
    Then every question went to Context7 with the library and the pinned version
    And the results are scored with the text scorer next to ExactDocs' configurations, with intervals

  Scenario: A version Context7 does not serve is asked unpinned and reported as latest only
    Given a stand-in for Context7 that serves only the library's current documentation
    When the run resolves each pinned version in Context7 and asks its questions
    Then the report states that Context7 does not serve the version
    And its questions are asked without a version and reported as latest only, apart from the pinned numbers

  Scenario: Scoring is rerun from the cached responses
    Given a stand-in for Context7 that serves the pinned version
    And the run resolved each pinned version in Context7 and asked its questions
    When the run is repeated from its cache of Context7's responses
    Then Context7 is not called again
    And the results are the same
