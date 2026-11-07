Feature: The retrieval mode is chosen per call, library and instance, from what is configured
  As an operator, a library contributor and an AI agent
  I want each search to use the mode asked for, else the library's, else the instance's
  So that one size need not fit every documentation set, and an unavailable mode fails clearly

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: Precedence is call, then library, then instance
    Given the instance mode is "bm25" and the library's mode is "hybrid"
    When an agent searches with mode "bm25"
    Then the result says retrieval mode "bm25"

  Scenario: Without a mode in the call, the library's mode answers
    Given the instance mode is "bm25" and the library's mode is "hybrid"
    When an agent searches without a mode
    Then the result says retrieval mode "hybrid"

  Scenario: Without a library mode, the instance's mode answers
    Given the instance mode is "bm25" and an embedding model is configured
    When an agent searches without a mode
    Then the result says retrieval mode "bm25"

  Scenario: An unavailable mode fails clearly
    Given no embedding model is configured
    When an agent searches with mode "hybrid"
    Then the call fails with "mode_unavailable" naming the missing role "embedding"

  Scenario: A library mode needs its model
    Given no embedding model is configured
    When the admin sets the library's mode to "hybrid"
    Then the call fails with "mode_unavailable" naming the missing role "embedding"
    And the library has no mode of its own
