Feature: Coding-agent CLIs run headless with and without a documentation MCP server
  As a maintainer telling users whether a documentation tool helps the coding agent they use
  I want the benchmarks to drive real coding-agent CLIs, each run isolated, with one documentation arm
  So that a harness's own prompts, tools and context decide whether the docs server is called, and at what cost

  Background:
    Given a coding CLI that runs headless, coding tasks pinning a stand-in library at 1.0 and 2.0, and its model

  Scenario: A coding CLI runs a task headless with one documentation arm
    When the CLI runs each task headless behind its gate with the "exactdocs" arm's MCP configuration
    Then its transcript is parsed into tool calls, MCP calls, wall time, input tokens, output tokens including thinking, and thinking tokens where the CLI reports them
    And the workspace is evaluated with the coding-task evaluators
    And the gate let the run reach only the arm's MCP server

  Scenario: With and without the MCP server, on the same tasks
    When the CLI runs each task in the "none" arm and in the "exactdocs" arm
    Then the report compares pass rate, wall time and output tokens of the two arms on the same tasks, with a paired test
    And it gives the share of runs that called the docs server and the docs calls per task, with intervals

  Scenario: The harness's own web access does not leak into the arms
    When each harness is configured for the "none", "exactdocs", "context7" and "grounded-docs" arms
    Then its built-in web search and fetch are off, so the arms differ only by the MCP server
    And a web call or a host the gate refused would be counted in the report
