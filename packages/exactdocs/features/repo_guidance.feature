Feature: The repository's AGENTS.md / CLAUDE.md guide agentic retrieval
  As a library owner
  I want the repository's instruction files to guide the agentic search
  So that the agent finds answers faster where the files describe how the docs are organized

  The files are repository content, so untrusted: they reach the agent as user-channel notes, and
  as system instructions only when the owner marks the library trusted. The LLM is a scripted
  pydantic-ai FunctionModel that records what it receives: no provider is called.

  Background:
    Given ExactDocs imports the fixture docs repository

  Scenario: Instruction files are untrusted notes by default
    Given the library's repository has an AGENTS.md describing its docs layout
    And the owner enabled repo guidance without marking the library trusted
    When the agent opens a directory
    Then the file reaches it as a user-channel note, not as system instructions

  Scenario: A trusted library's root file is part of the agent's instructions
    Given the library's repository has an AGENTS.md describing its docs layout
    And the owner enabled repo guidance and marked the library trusted
    When the agent opens a directory
    Then the file is part of its system instructions

  Scenario: Without repo guidance the agent gets no instruction file
    Given the library's repository has an AGENTS.md describing its docs layout
    And the owner left repo guidance off
    When the agent opens a directory
    Then no instruction file reaches it
