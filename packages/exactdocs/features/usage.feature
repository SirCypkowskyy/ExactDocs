Feature: Usage is counted per day, with a libraries leaderboard and an opt-in people leaderboard
  As a platform team running ExactDocs
  I want to see which libraries are read most and, only when people agree, who uses it how much
  So that we know which docs matter, without monitoring anyone who did not opt in

  Scenario: Reads are counted per day
    Given ExactDocs is running with the fixture docs repository imported as "/acme/docs"
    And "alice" is a viewer of "/acme/docs"
    When an agent reads two articles of "/acme/docs" over MCP with alice's token
    And the agent searches "/acme/docs" for "retry_policy" over MCP with alice's token
    Then the usage counts for today show 2 reads for alice, that token and "/acme/docs"
    And no query text or content is stored, only counts

  Scenario: The libraries leaderboard
    Given ExactDocs is running with the fixture docs repository imported as "/acme/docs" and "/beta/docs"
    And "alice" is a viewer of "/acme/docs"
    And "alice" is a viewer of "/beta/docs"
    And last week "/beta/docs" was read 5 times and "/acme/docs" 2 times
    When alice reads "/acme/docs" 3 times and "/beta/docs" once this week
    And an operator asks for the most-read libraries this week
    Then they get "/acme/docs" ranked 1st, 2nd the week before, and "/beta/docs" ranked 2nd, 1st the week before

  Scenario: The people leaderboard is opt-in
    Given ExactDocs is running with the people leaderboard turned on and the fixture docs repository imported as "/acme/docs"
    And "alice" is a viewer of "/acme/docs"
    And "bob" is a viewer of "/acme/docs"
    And alice opted in to the people leaderboard
    And bob did not opt in
    When alice reads "/acme/docs" once and bob reads it twice
    Then bob appears on no people leaderboard
    And nobody sees his counts except operators in aggregate

  Scenario: The people leaderboard is off until the operator turns it on
    Given ExactDocs is running with the fixture docs repository imported as "/acme/docs"
    And "alice" is a viewer of "/acme/docs"
    And alice opted in to the people leaderboard
    When alice reads "/acme/docs" once
    Then the people leaderboard is refused to alice and to the operator
    But the libraries leaderboard ranks "/acme/docs" for alice
