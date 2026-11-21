Feature: Libraries declared in a sources file
  As an operator running ExactDocs for several products
  I want the set of imported docs declared in exactdocs.sources.yaml and applied with a dry-run diff
  So that it goes through code review and a second instance can be rebuilt from it

  Background:
    Given a fresh instance
    And the admin "ada" was set up with the password "correct horse battery staple"
    And the instance is served on a loopback port
    And the user is logged in with the CLI
    And a sources file declaring "/fixture/docs-repo" at ref "main" with tag pattern "v*" and include path "docs"

  Scenario: Plan shows the diff and changes nothing
    Given an instance with no libraries
    When the operator runs "exactdocs sources plan exactdocs.sources.yaml"
    Then the command succeeds
    And the output lists "/fixture/docs-repo" under "create"
    And the instance still has no libraries and no jobs

  Scenario: Apply is idempotent
    When the operator runs "exactdocs sources apply exactdocs.sources.yaml"
    Then the command succeeds
    And "/fixture/docs-repo" exists with include path "docs" and an auto-sync with tag pattern "v*"
    And an import of "main" is queued
    When the operator runs "apply" again
    Then the second apply reports no changes and queues no job

  Scenario: Undeclared libraries are listed, and removed only with prune
    Given the instance also has the library "/fixture/other-repo", which the file does not declare
    When the operator runs "exactdocs sources apply exactdocs.sources.yaml"
    Then "/fixture/other-repo" is listed under "undeclared" and still exists
    When the operator runs "exactdocs sources apply exactdocs.sources.yaml --prune"
    Then "/fixture/other-repo" is removed

  Scenario: An entry declares its own title and description
    Given the sources file also declares the title "Azure Functions" and the description "Functions docs."
    When the operator runs "exactdocs sources apply exactdocs.sources.yaml"
    Then "/fixture/docs-repo" has the title "Azure Functions" and the description "Functions docs."
    When the sources file declares the title "Azure Functions 2"
    And the operator runs "exactdocs sources plan exactdocs.sources.yaml"
    Then the output lists "/fixture/docs-repo" under "update"
    And the output shows the title changing to "Azure Functions 2"
    When the operator runs "exactdocs sources apply exactdocs.sources.yaml"
    Then "/fixture/docs-repo" has the title "Azure Functions 2" and the description "Functions docs."

  Scenario: An entry without title and description leaves them alone
    When the operator runs "exactdocs sources apply exactdocs.sources.yaml"
    Then the library "/fixture/docs-repo" was named by its README
    When the operator runs "exactdocs sources plan exactdocs.sources.yaml"
    Then the output lists "/fixture/docs-repo" under "unchanged"
