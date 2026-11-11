Feature: A cross-encoder reranker reorders the top candidates
  As an operator and an AI agent
  I want a reranker endpoint to reorder the best candidates of a search
  So that agents read the right section first, and a reranker outage never breaks search

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: A reranker timeout never fails the search
    Given a reranker endpoint that times out
    When an agent searches "how do I retry failed calls"
    Then results arrive in the unreranked order with "reranked: false" and a fallback reason

  Scenario: Reranking reorders the top candidates
    Given a reranker is configured
    When an agent searches "how do I retry failed calls"
    Then the result says "reranked: true" and the candidates are ordered by the reranker's score
    And the reranker was sent the query and the candidates' chunk text only

  Scenario: A TEI reranker reorders the top candidates
    Given a TEI reranker is configured
    When an agent searches "how do I retry failed calls"
    Then the result says "reranked: true" and the candidates are ordered by the reranker's score

  Scenario: A library reranks its own number of candidates
    Given a reranker is configured
    And the admin sets the library's rerank top N to 3
    When an agent searches "how do I retry failed calls"
    Then the result says "reranked: true" and only the top 3 candidates were sent to the reranker
