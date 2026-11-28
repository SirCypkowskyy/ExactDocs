Feature: A default library role lets every account read every library
  As the operator of an instance whose docs everyone may read
  I want one setting that makes every account a viewer of every library
  So that I don't share each library with each person, now and as libraries and people are added

  Scenario: an account nobody shared anything with reads every library and changes nothing
    Given ExactDocs is running with "viewer" as the default library role, library creation left to operators, and the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And "bob" has no role on "/fixture/docs-repo"
    Then "bob" can search and read it in the UI and over MCP
    But changing its paths is refused
    And "bob" is not offered the MCP tools that add libraries
    And the Users page says "bob"'s role comes from the default library role, read-only
