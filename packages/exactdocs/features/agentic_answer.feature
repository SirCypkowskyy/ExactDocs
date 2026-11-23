Feature: An agent answers a question from chosen libraries, with its sources
  As an operator checking whether the agent can answer a cross-library question
  I want a written answer over the libraries I choose, with the sources it stands on
  So that I can follow each source to the article, and see what the run cost and how far it got

  The LLM is a scripted pydantic-ai FunctionModel: no provider is called. It searches its
  libraries and reads a chunk inside run_code, then answers with its sources.

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And the fixture docs repository is also imported as "/other/guide" at "v1.3.0"

  Scenario: Agentic answer with sources
    Given an LLM that answers from what it reads is configured
    When a user asks "how do I retry failed calls" over "/fixture/docs-repo" and "/other/guide"
    Then the answer is written and lists its sources
    And every source is from a chosen library's default version, with a link to its article
    And the run reports its tool calls out of the limit, and its tokens

  Scenario: Progress is streamed while the agent works
    Given an LLM that answers from what it reads is configured
    When a user asks "how do I retry failed calls" over all libraries, streaming the progress
    Then progress events count the tool calls out of the limit, then the answer arrives

  Scenario: The agent stays within its tool-call limit
    Given answers are limited to 20 tool calls
    When a user asks "how do I retry failed calls" over all libraries
    Then there is no answer, with the reason "agent_limit_reached"
    And every source is from a chosen library's default version, with a link to its article

  Scenario: The agent stops when the budget is used up
    Given an LLM that answers from what it reads is configured, with its daily token budget used up
    When a user asks "how do I retry failed calls" over all libraries
    Then there is no answer, with the reason "llm_budget_reached", and no model was called

  Scenario: The agent stops when the caller is over the LLM search rate limit
    Given an LLM that answers from what it reads is configured, limited to 2 LLM searches per minute
    And a user has already asked "how do I retry failed calls" over all libraries 2 times
    When a user asks "how do I retry failed calls" over all libraries
    Then there is no answer, with the reason "llm_rate_limited", and no model was called

  Scenario: A token limited to one library reaches only that library
    Given an LLM that answers from what it reads is configured
    And an API token limited to "/fixture/docs-repo"
    When the token searches all libraries for "retry"
    Then every result of the token is from "/fixture/docs-repo"
    When the token asks "how do I retry failed calls" over all libraries
    Then the answer is written and lists its sources
    And no source is from "/other/guide"
    And asking over "/other/guide" with the token is refused as not found, like a library that does not exist
    And searching "/other/guide" with the token is refused as not found, like a library that does not exist

  Scenario: A source outside the chosen libraries is never returned
    Given an LLM that also cites a chunk of "/other/guide" is configured
    When a user asks "how do I retry failed calls" over "/fixture/docs-repo"
    Then the answer is written and lists its sources
    And no source is from "/other/guide"

  Scenario: No LLM is configured
    When a user checks whether agentic answers are available
    Then they are not, because "no llm role is configured"
    And asking "how do I retry failed calls" is refused with "mode_unavailable"
