Feature: A retrieval benchmark compares modes, models and chunking on the golden set
  As a maintainer choosing the default retrieval configuration
  I want every configuration measured on the same golden set, per chunking configuration
  So that a default is chosen by numbers, with what it costs for each budget

  Background:
    Given a golden corpus with an answerable and an unanswerable question
    And stand-ins for the hosted models

  Scenario: Every retrieval configuration is measured on the same golden set
    When the retrieval benchmark runs every configuration at two chunking configurations
    Then each configuration that ran reports recall@1/5/10, MRR, nDCG@10, wrong-version rate, p50/p95 latency and tokens and USD per question
    And each metric is broken down by question kind and by project
    And each unanswerable question is scored on returning nothing of another version and on signalling no answer
    And each result records its models, its settings and the corpus commits

  Scenario: The benchmark names the best default for each budget
    When the retrieval benchmark runs every configuration at two chunking configurations
    Then the summary names the best configuration with no models, with local models only and with hosted models
    And each with its cost per 1000 questions
