Feature: Agentic retrieval browses the tree in Code Mode, justifies its answer and stays in bounds
  As an AI coding agent
  I want a question that needs reasoning over the docs' structure answered by an agent that reads them
  So that I get the sections that answer it, why, and how they were found, from the pinned version only,
  whatever the model does: a guardrail checks its answer and a loop ends its run

  The LLM is a scripted pydantic-ai FunctionModel: no provider is called. It drives Code Mode as an
  agent would (search, list the articles, read outlines and a chunk inside run_code), then answers.

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: Agentic mode returns justified articles from the pinned version
    Given an LLM is configured and agentic mode is on
    When an agent searches "/fixture/docs-repo/v1.4.0" in mode "agentic"
    Then results carry a justification and the explored path
    And every result belongs to "v1.4.0"

  Scenario: A run that exceeds its limits falls back
    Given agentic mode is limited to 20 tool calls
    When the agent needs more
    Then the run ends and the search answers with the best non-agentic mode and the reason "agent_limit_reached"

  Scenario: The output guardrail rejects foreign articles
    Given an LLM is configured and agentic mode is on
    When the agent proposes an article that is not in the pinned version
    Then the guardrail rejects it and it is not returned
    And every result belongs to "v1.4.0"

  Scenario: A looping agent is stopped
    Given an LLM is configured and agentic mode is on
    When the agent calls the same tool with the same arguments 3 times
    Then the run ends and the search falls back to BM25 with the reason "agent_loop_detected"
