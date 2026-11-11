Feature: Similar agentic questions are answered from a cache
  As an AI coding agent
  I want a question asked again in other words answered from the earlier agentic answer
  So that I get it at once, without the cost of another agent run, and never from another version

  The LLM is a scripted pydantic-ai FunctionModel: no provider is called. No embedding model is
  configured, so the operator turned the cache on explicitly and questions are compared by their
  words (BM25 term weights): only questions with the same terms, numbers and negations match.

  Scenario: A similar question hits the cache
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And an LLM is configured, agentic mode is on and the agentic cache is on
    And "how do I configure retries" was answered agentically for "v1.4.0"
    When an agent asks "how to configure retry behaviour" for "v1.4.0"
    Then the cached result is returned with "cache_hit: true"
    And the agent did not run again
    And every result belongs to "v1.4.0"

  Scenario: A cached answer never answers another version
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And an LLM is configured, agentic mode is on and the agentic cache is on
    And "how do I configure retries" was answered agentically for "v1.4.0"
    When an agent asks "how to configure retry behaviour" for "v1.3.0"
    Then the agent runs again and the result says "cache_hit: false"

  Scenario: A negated question runs the agent again
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And an LLM is configured, agentic mode is on and the agentic cache is on
    And "why are failed calls retried" was answered agentically for "v1.4.0"
    When an agent asks "why are failed calls not retried" for "v1.4.0"
    Then the agent runs again and the result says "cache_hit: false"

  Scenario: A re-sync invalidates the cache
    Given ExactDocs imports the fixture docs repository
    And the fixture repository is a private copy
    And "/fixture/docs-repo/main" is imported
    And a cached agentic answer for "main"
    When "main" is re-synced to a new commit
    Then the next similar question runs the agent again
