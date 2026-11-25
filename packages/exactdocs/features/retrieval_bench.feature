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

  Scenario: A chunk that holds the expected section is a hit at any chunking
    Given a golden case whose expected section a chunking merges into the chunk of the section before it
    When the retrieval benchmark runs BM25 at that chunking
    Then the case counts as a hit at the rank of that chunk

  Scenario: Any answering section is a hit
    Given a case whose answer is in section A or, equally, in section B
    When a tool returns B in its top 5 and not A
    Then the case counts as a hit for recall@5

  Scenario: A multi-page answer still needs every part
    Given a cross-page case that needs sections A and C
    When a tool returns only A
    Then recall@5 counts the case, and section recall shows that C is missing

  Scenario: Recall within a token budget of the text returned
    When the retrieval benchmark runs every configuration at two chunking configurations
    Then each configuration that ran reports the context it returned per question and recall within the first 1,000, 2,000 and 4,000 tokens of it
    And each is tested against its budget's default
    And the summary shows recall within each budget

  Scenario: The benchmark names the best default for each budget
    When the retrieval benchmark runs every configuration at two chunking configurations
    Then the summary names the best configuration with no models, with local models only and with hosted models
    And each with its cost per 1000 questions

  Scenario: Each metric comes with an interval
    Given a recorded retrieval run on the golden set
    When the report is rendered
    Then recall@k, MRR and nDCG@10 of each configuration show a 95% confidence interval
    And the report records the seed and the number of resamples

  Scenario: A dearer default needs a significant gain
    Given configuration B beats the budget default A by more than the margin on recall@5
    And the paired test of B against A on the same cases is not significant at 5%
    When the defaults are chosen
    Then A stays the default and the reason says the difference is not significant
