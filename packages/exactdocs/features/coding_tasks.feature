Feature: Version-pinned coding tasks check that an agent's code runs against the pinned version
  As a maintainer telling users whether a documentation tool helps their coding agent
  I want coding tasks whose hidden tests run against the exact version a project pins
  So that code written for another version is caught, and the report names what it got wrong

  Background:
    Given coding tasks over a stand-in library, one pinning version 1.0 and one version 2.0

  Scenario: A task passes only when its tests pass against the pinned version
    Given a task workspace that pins demo 1.0 and asks for a model with a custom validator
    When an agent completes the task
    Then the hidden tests run in a sandbox with exactly that version installed
    And the task passes only when they pass

  Scenario: Code for another version is caught
    Given a task workspace that pins demo 2.0 and asks for a model with a custom validator
    And a reference solution written for the other major version
    When it is evaluated on the task
    Then the task fails, and the report names the API that does not exist in the pinned version

  Scenario: Every reference passes and every other-version solution fails, without a model
    When the tasks are checked without a model
    Then each reference passes on its pinned version and each other-version solution fails naming a forbidden API

  Scenario: Agents complete the tasks with workspace tools and a documentation arm
    When scripted agents complete the tasks with the arms "none" and "exactdocs"
    Then every agent works through the workspace tools, and only the "exactdocs" arm also has documentation tools
    And the report gives the pass rate, the forbidden-API rate and the files changed per task, project and arm, with intervals
    And the "exactdocs" arm is compared with "none" on the same tasks by a paired test

  @integration
  Scenario: The Pydantic 1.10.22 task runs against Pydantic 1.10.22
    Given the task workspace that pins pydantic 1.10.22 and asks for a model with a custom validator
    When its reference solution and the solution written for Pydantic 2 are evaluated
    Then the hidden tests ran with pydantic 1.10.22 installed, the reference passes, and the Pydantic 2 solution fails naming "field_validator"
