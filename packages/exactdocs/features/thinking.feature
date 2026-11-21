Feature: Operators set the thinking level of the llm and judge models
  As an operator paying for the thinking tokens of every LLM call
  I want to lower how much the llm and judge models think before they answer
  So that HyDE, the judge and the agentic mode cost and take no more than their short work needs

  The models are on a fake gateway on loopback, called through pydantic-ai: the Gemini API for
  the llm role (its thinking level is Google's `thinking_level`) and an OpenAI-compatible gateway
  for the judge (its level is `reasoning_effort`), so each request is the one a provider gets.

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: An operator sets a low thinking level for the llm role
    Given the llm role is a Gemini model with thinking level "low"
    When a hybrid_hyde search runs
    Then the model is called with Google's thinking level "LOW"
    And the instance's roles show the llm role's thinking level as "low"

  Scenario: Unset keeps today's behavior
    Given the llm role is a Gemini model with no thinking level
    When a hybrid_hyde search runs
    Then the model is called without a thinking setting

  Scenario: A library uses its own judge with its own thinking level
    Given the llm role is a Gemini model with thinking level "low"
    And the library's retrieval settings set its own judge with thinking level "minimal"
    When its search is reranked by the judge
    Then the judge is called with reasoning effort "minimal"
    And the library's retrieval settings show the judge's thinking level as "minimal"
    And the instance's roles show the llm role's thinking level as "low"

  Scenario: A level the model cannot take is refused
    Given the llm role is a Gemini model with no thinking level
    When the admin saves thinking level "high" for the library's own llm "gemini-2.0-flash"
    Then the save is refused with "thinking_unsupported" naming the role "llm" and the model "gemini-2.0-flash"

  Scenario: An admin sets the judge's thinking level over the REST API
    Given the llm role is a Gemini model with thinking level "low"
    When the admin sets the instance judge role's thinking level to "medium"
    Then the instance's roles show the judge role's thinking level as "medium"
    And setting the llm role's thinking level over the REST API is refused as configured
