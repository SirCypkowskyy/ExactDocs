Feature: Libraries and tokens from the command line
  As a user of a remote instance
  I want to add, list, sync and remove libraries and manage tokens with the CLI
  So that I can script an instance without the web UI

  Background:
    Given a fresh instance
    And the admin "ada" was set up with the password "correct horse battery staple"
    And the instance is served on a loopback port
    And the user is logged in with the CLI

  Scenario: Adding a library from the CLI
    When the user runs the command "exactdocs add <fixture-url> --id /fixture/docs-repo --ref v1.4.0 --path docs/ --wait"
    Then the command succeeds
    And "exactdocs libraries" lists "/fixture/docs-repo" with version "v1.4.0"
    And the REST API returns the same library as for a library added in the UI

  Scenario: Scripts get JSON and progress stays off stdout
    When the user runs the command "exactdocs add <fixture-url> --ref v1.4.0 --path docs/ --wait --json"
    Then the command succeeds
    And stdout is JSON that names the job and its state "succeeded"
    And stderr shows the import progress

  Scenario: A dry run from the CLI lists files without storing anything
    When the user runs the command "exactdocs add <fixture-url> --ref v1.4.0 --path 'docs/**' --dry-run"
    Then the command succeeds
    And the output lists the files the preview matches, with their count
    And the instance holds no library and no job

  Scenario: A dry run gives scripts the preview as JSON
    When the user runs the command "exactdocs add <fixture-url> --ref v1.4.0 --path 'docs/**' --dry-run --json"
    Then the command succeeds
    And stdout is JSON with the files, their total and whether the list was cut

  Scenario: Another version is added to a library
    Given the user ran the command "exactdocs add <fixture-url> --ref v1.3.0 --path docs/ --wait"
    When the user runs the command "exactdocs version add /fixture/docs-repo v1.4.0 --wait"
    Then the command succeeds
    And "exactdocs libraries" lists "/fixture/docs-repo" with version "v1.4.0"

  Scenario: A tag is not moved by sync
    Given the user ran the command "exactdocs add <fixture-url> --ref v1.3.0 --path docs/ --wait"
    When the user runs the command "exactdocs sync /fixture/docs-repo"
    Then the command succeeds
    And the output says "pinned"

  Scenario: Removal asks first and --yes skips the question
    Given the user ran the command "exactdocs add <fixture-url> --ref v1.3.0 --path docs/ --wait"
    When the user runs the command "exactdocs remove /fixture/docs-repo" without a terminal
    Then the command exits with code 2
    And "exactdocs libraries" lists "/fixture/docs-repo" with version "v1.3.0"
    When the user runs the command "exactdocs remove /fixture/docs-repo/v1.3.0 --yes"
    Then the command succeeds
    And the output says "Removed v1.3.0"
    When the user runs the command "exactdocs remove /fixture/docs-repo --yes"
    Then the command succeeds

  Scenario: Exit codes tell what went wrong
    When the user runs the command "exactdocs remove /nobody/nothing --yes"
    Then the command exits with code 3
    When the user runs the command "exactdocs add <fixture-url> --ref v9.9.9 --path docs/"
    Then the command exits with code 2

  Scenario: A duplicate library is a conflict
    Given the user ran the command "exactdocs add <fixture-url> --id /fixture/docs-repo --ref v1.3.0 --path docs/ --wait"
    When the user runs the command "exactdocs add <fixture-url> --id /fixture/docs-repo --ref v1.3.0 --path docs/"
    Then the command exits with code 4

  Scenario: Tokens are managed with the password, because a token cannot
    When the user runs the command "exactdocs token create ci --no-expiry" as the admin
    Then the command succeeds
    And the output holds a new token that the server accepts
    When the user runs the command "exactdocs token list" as the admin
    Then the output says "ci"
    When the user revokes the token "ci" as the admin
    Then the command succeeds
    And the revoked token is refused by the server

  Scenario: A wrong password creates nothing
    When the user runs the command "exactdocs token create ci" as the admin with a wrong password
    Then the command exits with code 5
