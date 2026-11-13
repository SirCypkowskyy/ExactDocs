Feature: An ingestion benchmark measures how the golden corpus is chunked
  As a maintainer choosing chunking settings
  I want coverage, integrity, chunk sizes and heading paths measured on real docs per configuration
  So that a chunking change is judged by numbers, next to the retrieval recall it leads to

  Background:
    Given a golden corpus whose docs hide a heading in MDX code and keep a heading id in its text

  Scenario: The ingestion benchmark reports how well each project was chunked
    When the ingestion benchmark runs with today's default chunking
    Then it reports, for the project's version, the coverage of the expected sections
    And the chunks that cut a code block, table or list in two
    And the distribution of chunk sizes in tokens
    And how many chunks have an empty or wrong heading path

  Scenario: Chunking configurations are compared side by side
    When the ingestion benchmark runs the "default" and "h2" chunking configurations
    Then one table compares them on every metric and on BM25 recall@5
