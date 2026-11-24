Feature: An independent review states how often the golden set's cases are wrong
  As a maintainer publishing comparisons on the golden set
  I want a critically reviewed, stratified sample of its cases and checks over its wording
  So that a reader knows how far to trust the set, and whether its questions favour keyword search

  Background:
    Given a golden set with one case of every kind over a small pinned docs project

  Scenario: A critically reviewed sample bounds the set's error rate
    When the review sample is drawn with one case per kind and project
    Then the review sheet shows every sampled case with links to its source at the pinned commit
    And each sampled case is recorded as correct, fixed or removed, with the reviewer, the date and the reason
    And the review summary states the share of wrong cases with a confidence interval and who reviewed them

  Scenario: Lexical leakage is measured on the whole set
    When the whole-set checks of the golden set run
    Then they report how much each question's wording overlaps its expected section against the other sections
    And the cases whose question copies its section's wording are listed
