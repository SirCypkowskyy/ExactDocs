Feature: Checking a repository before adding it
  As a user adding a library
  I want to paste a git URL and learn at once whether it works
  So that I fix a wrong URL before anything is saved

  Background:
    Given ExactDocs is running with the demo catalog

  Scenario Outline: Common git URLs are accepted with a default ID
    When a user checks the repository URL "<url>"
    Then it is accepted with the proposed library ID "<id>"

    Examples:
      | url                                           | id                 |
      | https://github.com/acme/orders                | /acme/orders       |
      | https://bitbucket.org/acme/billing            | /acme/billing      |
      | https://gitlab.com/acme/platform/sub/docs     | /acme/docs         |
      | https://git.example.com/acme/handbook.git     | /acme/handbook     |
      | git@git.example.com:acme/orders.git           | /acme/orders       |
      | file://<fixtures>/fixture/docs-repo           | /fixture/docs-repo |
      | http://127.0.0.1:<port>/fixture/docs-repo.git | /fixture/docs-repo |

  Scenario: A taken ID asks for another one
    Given library "/acme/payments" exists from GitHub
    When a user checks "https://bitbucket.org/acme/payments"
    Then the user is asked to choose another library ID
    And the answer names the library "/acme/payments"

  Scenario: The repository's default branch is reported
    When a user checks the repository URL "http://127.0.0.1:<port>/fixture/docs-repo.git"
    Then the default branch is "main"

  Scenario Outline: A URL that cannot work is explained
    When a user checks "<url>"
    Then the check fails with "<error>"

    Examples:
      | url                                      | error                  |
      | http://127.0.0.1:1/acme/gone.git         | repository_unreachable |
      | file:///nonexistent/acme/gone            | not_a_git_repository   |
      | payments                                 | invalid_repository_url |

  Scenario Outline: A URL cannot smuggle options, commands or credentials into git
    When a user checks "<url>"
    Then the check fails with "invalid_repository_url"
    And the answer does not repeat "<secret>"

    Examples:
      | url                                           | secret         |
      | --upload-pack=touch /tmp/exactdocs-pwned      | exactdocs-pwned |
      | ext::sh -c touch% /tmp/exactdocs-pwned        | exactdocs-pwned |
      | https://user:hunter2@git.example.com/acme/x   | hunter2        |
