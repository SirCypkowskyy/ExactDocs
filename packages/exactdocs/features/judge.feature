Feature: A judge model can rerank candidates
  As an operator without a cross-encoder endpoint
  I want a small, fast LLM to rate each candidate's relevance
  So that agents read the right section first, while the judge stays bounded, budgeted and
  unable to invent results

  The judge is an OpenAI-compatible profile on a fake gateway on loopback, called through
  pydantic-ai: it rates the candidates of its prompt with the last one best, so a judged order is
  easy to tell from the order the search found. It reranks only libraries that chose it.

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: The judge reorders the top candidates in one call
    Given a judge model is configured and the library reranks with the judge
    When an agent searches "how do I retry failed calls"
    Then the result says "reranked: true" and the candidates are ordered by the judge's ratings
    And the judge was called once with the query and the candidates as delimited, untrusted text

  Scenario: The judge only rates candidates it was given
    Given a judge model is configured and the library reranks with the judge
    When the judge model returns a chunk ID it was not given
    Then the output validator rejects it and the search falls back to the unreranked order

  Scenario: The judge stays within budget
    Given a judge model is configured and the library reranks with the judge
    And the library's daily LLM budget is used up
    When an agent searches with the judge configured
    Then results arrive unreranked with "reranked: false" and fallback reason "llm_budget_reached"
    And the judge was not called

  Scenario: The cross-encoder reranks unless the library chooses the judge
    Given a reranker and a judge model are configured
    When an agent searches "how do I retry failed calls"
    Then the cross-encoder reranked the candidates and the judge was not called
    When the admin sets the library to rerank with the judge
    And an agent searches "how do I retry failed calls"
    Then the result says "reranked: true" and the candidates are ordered by the judge's ratings
