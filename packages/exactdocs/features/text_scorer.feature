Feature: The retrieval benchmark scores any documentation tool's text results
  As a maintainer comparing ExactDocs with tools that return text, not chunk IDs
  I want a tool's text results scored on the golden set from the text alone
  So that every tool is measured on the same questions, versions and metrics

  Background:
    Given a project whose docs are pinned at two versions

  Scenario: A text result that holds the expected section is a hit
    Given a case whose expected section S belongs to version V
    And a tool returned text results for the question
    When the results are scored
    Then the first result whose text holds S's text counts as a hit at its rank

  Scenario: A text result that holds an alternative section is a hit
    Given a case whose answer is in section S or, equally, in section T of version V
    And a tool returned text results for the question that hold T and not S
    When the results are scored
    Then the first result whose text holds T counts as a hit at its rank

  Scenario: Text that exists only in another version is a wrong-version result
    Given a result whose text matches a section of another pinned version and no section of V
    When the results are scored
    Then the case counts towards the wrong-version rate

  Scenario: Text shared by several versions is neither
    Given a result whose text is identical in V and in another pinned version
    When the results are scored
    Then it is counted as version-neutral, not as wrong-version
