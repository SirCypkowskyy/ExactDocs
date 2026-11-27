Feature: Adding libraries from an MCP client
  As someone who may create libraries
  I want my agent to add a missing library or version, and see how its import goes
  So that I never leave the agent to fill a gap in the index

  Background:
    Given ExactDocs serves the fixture repository as "https://github.com/fixture/docs-repo", and group "docs-admins" may create libraries

  Scenario: People who may not create libraries never see the tools
    Given "bob" is a user outside every creator group
    When "bob" lists the MCP tools
    Then the tools hold no "add_docs" and no "import_status"
    And "bob" calling "add_docs" gets the answer of a tool that does not exist

  Scenario: A token limited to some libraries does not see the tools, even an admin's
    Given the admin has an agent token limited to "/acme/payments"
    When the admin lists the MCP tools
    Then the tools hold no "add_docs" and no "import_status"

  Scenario: A member of a creator group adds a new library from its URL
    Given "bob" belongs to the creator group "docs-admins"
    When "bob" lists the MCP tools
    Then the tools hold "add_docs" and "import_status"
    When "bob" calls add_docs with source "https://github.com/fixture/docs-repo" and ref "next"
    Then the answer is one line "queued /fixture/docs-repo@next (<sha of next>), job <job>"
    And the job records "bob" as who queued it, over MCP
    And the library "/fixture/docs-repo" takes the paths of its context7.json
    And the access log records that "bob" created "/fixture/docs-repo"

  Scenario: The shorthand names a GitHub repository, and a ref of an existing library adds that version
    Given the admin added "fixture/docs-repo" over MCP
    When the admin calls add_docs with source "fixture/docs-repo" and ref "v1.3.0"
    Then the answer is one line "queued /fixture/docs-repo@v1.3.0 (<sha of v1.3.0>), job <job>"

  Scenario: Repeating a call queues nothing more
    Given the admin added "fixture/docs-repo" over MCP
    When the admin calls add_docs with source "fixture/docs-repo" and ref "v1.4.0"
    And the admin calls add_docs with source "fixture/docs-repo" and ref "v1.4.0" again
    Then the second answer names the first job as already importing
    And the library has one import job for "v1.4.0"
    When the imports finish
    And the admin calls add_docs with source "/fixture/docs-repo" and ref "1.4.0"
    Then the answer is one line "already indexed: /fixture/docs-repo@v1.4.0 (<sha of v1.4.0>)"

  Scenario: An existing library and no ref re-syncs it
    Given the admin added "fixture/docs-repo" over MCP
    And the imports finish
    When the admin calls add_docs with source "/fixture/docs-repo"
    Then the answer has the line "main: up_to_date"

  Scenario: The agent follows its imports
    Given the admin added "fixture/docs-repo" over MCP
    When the imports finish
    And the admin calls import_status with that job
    Then the answer is one line starting "succeeded: /fixture/docs-repo@main, files"
    When the admin calls import_status with no job
    Then the answer has at most 5 lines, each a job the admin queued

  Scenario Outline: A disallowed source is refused before anything is fetched
    When the admin calls add_docs with source "<source>"
    Then the answer is the error "source_not_allowed"
    And no git command ran

    Examples:
      | source                     |
      | file:///etc                |
      | ssh://git@internal/x.git   |
      | git@github.com:a/b.git     |
      | http://169.254.169.254/    |
      | https://10.0.0.5/repo.git  |
      | https://u:p@github.com/a/b |
      | https://github.com:8443/a/b |
      | https://evil.example/a/b   |

  Scenario: An allowed host whose name resolves to a private address is refused
    Given the operator allows imports over MCP from "git.internal"
    And "git.internal" resolves to "10.0.0.5"
    When the admin calls add_docs with source "https://git.internal/team/docs"
    Then the answer is the error "source_not_allowed"
    And no git command ran

  Scenario: A URL whose library ID is taken by another repository is refused
    Given the admin added "fixture/docs-repo" over MCP
    When the admin calls add_docs with source "https://gitlab.com/fixture/docs-repo"
    Then the answer is the error "library_exists" naming "/fixture/docs-repo"
