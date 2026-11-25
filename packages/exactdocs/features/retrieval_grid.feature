Feature: The retrieval benchmark cross-tests chunking, context and embedding variants against plain baselines
  As a maintainer choosing how ExactDocs cuts, indexes and embeds documentation
  I want a declared grid of variants measured on the golden set next to plain baselines
  So that a variant only changes a default when it beats what ships, significantly

  Background:
    Given a golden corpus with an answerable and an unanswerable question

  Scenario: A declared grid is cross-tested on the golden set
    Given a grid of ingestion, index, retrieval and rerank settings in a file
    When the grid runs on the golden set
    Then every cell reports the retrieval metrics with intervals and its index cost
    And each cell is compared with the budget's default by the paired test
    And each eval-only chunker reports where it cut code blocks or tables

  Scenario: Plain baselines set the floor
    Given a grid of ingestion, index, retrieval and rerank settings in a file
    When the run includes the keyword-grep and fixed-window RAG baselines
    Then they are scored with the text scorer like any other tool

  Scenario: A grid run resumes per cell
    Given a grid of ingestion, index, retrieval and rerank settings in a file
    And a grid run that stopped after its first cell
    When the grid runs on the golden set
    Then the first cell is not run again and every other cell is
