Feature: An LLM endpoint enables HyDE for hybrid search
  As an AI coding agent
  I want my question turned into a short hypothetical answer before the vector half searches
  So that a question in my words finds the section written in the docs' words, in the pinned version

  HyDE is chosen by the operator here: it becomes a default only once the eval suite shows it
  beats BM25 with a real model (docs/evals/gates.md#becoming-a-default). The LLM is a fake OpenAI-compatible gateway on
  loopback, called through pydantic-ai; the embedding model is an in-process stand-in that hashes
  terms (free, so a budget stops the LLM step only).

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And an embedding model and an LLM are configured, and the operator chose retrieval mode "hybrid_hyde"

  Scenario: HyDE answers searches without a mode once embeddings and an LLM are configured
    Given every chunk of "v1.4.0" is embedded
    When an agent searches without a mode
    Then the result says retrieval mode "hybrid_hyde"
    And a repeated query for the same version reuses the cached hypothetical answer
    And every call to the LLM carried the profile's headers

  Scenario: HyDE respects the budget
    Given every chunk of "v1.4.0" is embedded
    And the instance's daily LLM budget is used up
    When an agent searches in "hybrid_hyde" mode
    Then the result says retrieval mode "hybrid" with fallback reason "llm_budget_reached"
    And the LLM was not called

  Scenario: An LLM that fails leaves hybrid search answering
    Given every chunk of "v1.4.0" is embedded
    And the LLM endpoint refuses every call
    When an agent searches in "hybrid_hyde" mode
    Then the result says retrieval mode "hybrid" with fallback reason "llm_unavailable"
