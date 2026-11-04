Feature: Version manifests
  As an AI coding agent
  I want a version's articles to change all at once, never piece by piece
  So that I never read half of a re-synced version

  Background:
    Given ExactDocs is running with the demo catalog
    And "/acme/payments" version "main" has the active manifest at commit "aaa111":
      | path               | title   | content          |
      | guide/install.md   | Install | install, old     |
      | guide/auth.md      | Auth    | auth             |
      | api/client.md      | Client  | client           |

  Scenario: Reading an article returns the active manifest, not a pending one
    Given "/acme/payments" version "main" has a pending manifest at commit "bbb222":
      | path               | title   | content          |
      | guide/install.md   | Install | install, new     |
    When I read the article "guide/install.md" of "/acme/payments" version "main"
    Then the response status is 200
    And the article says "install, old" at commit "aaa111"

  Scenario: Activating a manifest swaps the whole version at once
    Given "/acme/payments" version "main" has a pending manifest at commit "bbb222":
      | path               | title   | content          |
      | guide/install.md   | Install | install, new     |
      | guide/new.md       | New     | brand new        |
    When the pending manifest is activated
    And I read the article "guide/install.md" of "/acme/payments" version "main"
    Then the article says "install, new" at commit "bbb222"
    When I list the articles of "/acme/payments" version "main"
    Then the articles are "guide/install.md, guide/new.md" at commit "bbb222"
    When I request the version "/acme/payments/main"
    Then the version used is "main" of "/acme/payments"
    And the commit of the version is "bbb222"

  Scenario: Browsing without a ref uses the default version
    Given "/acme/payments" version "v1.4.0" has the active manifest at commit "ccc333":
      | path               | title   | content          |
      | guide/install.md   | Install | install, v1.4    |
    When I read the article "guide/install.md" of "/acme/payments" without a ref
    Then the article says "install, v1.4" at commit "ccc333"

  Scenario: Articles can be listed under a path prefix
    When I list the articles under "guide/" of "/acme/payments" version "main"
    Then the articles are "guide/auth.md, guide/install.md" at commit "aaa111"

  Scenario: A long list is paged with a cursor
    When I list 2 articles of "/acme/payments" version "main"
    Then the articles are "api/client.md, guide/auth.md" at commit "aaa111"
    And there is a next page

  Scenario: An article that is not in the version is not found
    When I read the article "guide/missing.md" of "/acme/payments" version "main"
    Then the response status is 404
    And the error code is "not_found"

  Scenario: A version without an active manifest has no articles
    When I read the article "guide/install.md" of "/acme/payments" version "next"
    Then the response status is 404
    And the error code is "not_found"
