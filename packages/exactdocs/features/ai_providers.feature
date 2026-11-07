Feature: Operators configure AI providers once per instance, with per-library overrides and sealed keys
  As an operator
  I want to name my model endpoints once and point every AI role at them
  So that keys stay sealed, never reach the wrong endpoint, and sensitive libraries stay local

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: A custom OpenAI-compatible gateway is configured once and used by every role
    Given the operator configures provider "corp" of kind "openai-compatible" with base URL "https://llm.example.com/v1" and a key
    And sets the LLM role to "corp:gpt-4.1-mini" and the embedding role to "corp:text-embedding-3-small"
    When the operator runs "exactdocs ai check"
    Then both roles report "ok" with the model name and the embedding dimensions
    And the key never appears in the output, the logs or the REST API

  Scenario: The SDKs' environment variables are never used
    Given the process environment has OPENAI_API_KEY, OPENAI_BASE_URL and ANTHROPIC_API_KEY set
    And provider "corp" of kind "openai-compatible" has no key
    When ExactDocs calls "corp"
    Then the request goes to corp's base URL with no OpenAI key, and nothing goes to OPENAI_BASE_URL

  Scenario: A library opts out of external AI
    Given provider "corp" is configured for every role
    When the admin sets library "/fixture/docs-repo" to AI "off"
    Then no chunk or query of that library is sent to any provider
    And searches in it answer with "bm25"

  Scenario: Nothing configured means nothing loaded
    Given no AI provider is configured
    When ExactDocs starts and serves searches
    Then no module of the "exactdocs[ai]" extra is imported and no outbound connection is opened
