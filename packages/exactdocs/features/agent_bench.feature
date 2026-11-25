Feature: The agent benchmark compares documentation arms
  As a maintainer telling users whether a documentation tool helps their coding agent
  I want the same model to answer the golden set with no documentation and with ExactDocs
  So that the gain in accuracy is weighed against the time and tokens it costs

  Background:
    Given a golden set with answerable and unanswerable questions
    And scripted agent models, one of them thinking, and a scripted judge

  Scenario: The same model answers the golden set with each documentation arm
    When the agent benchmark runs the arms "none" and "exactdocs"
    Then each arm gets the same prompt, the same usage limits and only its own tools
    And the instructions of the arms differ only in the sentence about the documentation tool
    And the report gives accuracy per arm, question kind and project, with intervals
    And the "exactdocs" arm is compared with "none" by a paired test

  Scenario: The cost of each arm is measured
    When the agent benchmark runs the arms "none" and "exactdocs"
    Then the report gives, per arm, the wall time per question, the input tokens and the output tokens including thinking, each as mean, p50 and p95 with an interval
    And the thinking tokens on their own where the model returns its thinking, marked estimated, and as not returned where it does not
    And a model without a price costs nothing known rather than zero
    And each arm's time and tokens are compared with the "none" arm on the same cases

  Scenario: The judge does not know the arm
    Given an answer that names ExactDocs and its tools
    When the answer is judged
    Then the judge sees the question, reference and answer only, with tool and product names removed

  Scenario: A provider failure is not a wrong answer
    Given the provider fails on one question
    When the agent benchmark runs the arms "none" and "exactdocs"
    Then that question is graded as an error in both arms and left out of the accuracy and the paired tests
    And a resumed run asks only that question again
