Feature: The retrieval benchmark measures Grounded Docs on the golden set
  As a maintainer comparing ExactDocs with the closest self-hosted alternative
  I want Grounded Docs to answer the golden set at the same pinned versions, scored as ExactDocs is
  So that the comparison uses the same docs, questions, metrics and intervals

  Background:
    Given a golden corpus with an answerable and an unanswerable question
    And a stand-in for Grounded Docs that replays its recorded responses

  Scenario: Grounded Docs answers the golden set at the pinned versions
    Given Grounded Docs at a pinned release has indexed every golden-corpus version from the same checkouts ExactDocs imports
    When each golden-set question is sent to its search for that library and version
    Then the results are scored with the text scorer
    And the report lists Grounded Docs next to ExactDocs' configurations with the same metrics and intervals
    And the report records Grounded Docs' version, its settings and the date

  Scenario: An article Grounded Docs leaves out is named, with the cases that expected it
    Given Grounded Docs leaves out an article a case expects
    When each golden-set question is sent to its search for that library and version
    Then the report names the article and the case
