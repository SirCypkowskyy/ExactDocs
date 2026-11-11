Feature: Admins see each library's AI pipeline, its spend limits and the instance's embedding progress
  As a library owner and an operator
  I want to see which pipeline answers for a library, pick another, cap what it spends, and see how far embedding has got
  So that I need neither logs nor /metrics to know what AI does for my documentation

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: The effective pipeline is visible
    Given an embedding model is configured and every version is embedded
    When the admin reads the library's retrieval settings
    Then the effective pipeline is "hybrid" and only "bm25, hybrid" can be chosen

  Scenario: A library can opt out of external AI
    Given an embedding model is configured and every version is embedded
    When the admin switches the library's AI to "off"
    Then the effective pipeline is "bm25" and the library uses no model role

  Scenario: Embedding progress is shown per space
    Given an embedding model is configured and every version is embedded
    When the admin reads the embedding progress
    Then the configured model's space is active and covers 2 of 2 versions and every chunk

  Scenario: A library's own budget is tighter than the instance's
    Given each library may spend 2 USD a day and the library's own daily budget is 1 USD
    And the library spent 1 USD today
    When a search needs an LLM step
    Then the step is skipped and the result names the cheaper mode with fallback reason "llm_budget_reached"
    And the AI usage shows the library's daily budget of 1 USD as reached

  Scenario: A library's budget may not be higher than the instance's
    Given each library may spend 2 USD a day
    When the admin sets the library's daily budget to 3 USD
    Then it is refused with "budget_above_instance" and the library keeps no budget of its own
