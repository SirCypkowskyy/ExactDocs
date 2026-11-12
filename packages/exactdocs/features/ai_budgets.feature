Feature: LLM usage is limited by budgets and rate limits
  As an operator paying for model calls
  I want hard limits per instance, library and user, and to see what was spent
  So that a misbehaving agent cannot run up the bill, and reaching a limit degrades search instead of breaking it

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: Reaching the daily budget falls back to the non-LLM pipeline
    Given the instance's daily LLM budget is used up
    When a search needs an LLM step
    Then the step is skipped and the result names the cheaper mode with fallback reason "llm_budget_reached"

  Scenario: Too many LLM searches per minute degrade instead of failing
    Given a caller is limited to 10 LLM searches per minute
    When it makes the 11th within a minute
    Then the result answers without the LLM step, with fallback reason "llm_rate_limited"

  Scenario: The embedding budget pauses embedding, not search
    Given the instance's monthly embedding budget is used up
    When an embed job runs
    Then it stops with "ai_budget_reached" before its next batch and is retried when the window resets
    And BM25 keeps answering for versions not yet embedded

  Scenario: A rerank call over budget is skipped
    Given the library's daily budget is used up and the reranker is a paid endpoint
    When an agent searches
    Then results arrive unreranked with "reranked: false" and fallback reason "llm_budget_reached"

  Scenario: Operators see what was spent and the budget left per scope
    Given the instance's daily LLM budget is used up
    When the admin reads the AI usage
    Then it shows the instance's spend today and that its daily budget is reached

  Scenario: A stdio process's LLM spend counts against the instance budget
    Given a stdio MCP process searches with an LLM step
    When the HTTP server reads the AI usage
    Then the spend of the stdio process is included
    And the instance's budget is reduced by it for every process
