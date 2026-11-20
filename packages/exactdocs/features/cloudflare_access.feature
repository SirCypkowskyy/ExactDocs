Feature: Cloudflare Access as the identity
  As an operator who publishes ExactDocs behind Cloudflare Access
  I want people and MCP clients that passed Access to be signed in by their Access identity
  So that nobody signs in twice and MCP clients need only the Access service token

  Background:
    Given the server is configured with Cloudflare Access team domain "https://team.cloudflareaccess.com" and audience "aud-123"

  Scenario: a person who passed Access is signed in without a second login
    Given a valid Access JWT for "alice@example.com" signed by the team's key
    When the browser asks for its session with it in the assertion header
    Then the state is "signed_in" as an account linked to "alice@example.com"
    And no password was asked for
    And the session is reported as coming from Cloudflare Access, with its sign-out address
    When the browser asks for its session with it in the Access cookie
    Then the state is "signed_in" as an account linked to "alice@example.com"

  Scenario: the same Access identity always reaches the same account
    Given a valid Access JWT for "alice@example.com" signed by the team's key
    And she has visited once
    When she visits again with a new Access JWT
    Then she reaches the account of her first visit

  Scenario: an admin is recognised by email
    Given "alice@example.com" is listed in admin_emails
    And a valid Access JWT for "alice@example.com" signed by the team's key
    When she arrives with a valid Access JWT
    Then her account has the role "admin"

  Scenario: without auto_create_users nobody new gets an account
    Given auto_create_users is off
    And a valid Access JWT for "alice@example.com" signed by the team's key
    When the browser asks for its session with it in the assertion header
    Then the session state is "signed_out"

  Scenario: a disabled account is refused
    Given a valid Access JWT for "alice@example.com" signed by the team's key
    And she has visited once
    And an operator disabled her account
    When the browser asks for its session with it in the assertion header
    Then the session state is "signed_out"

  Scenario: an MCP client with an Access service token needs no ExactDocs token
    Given service token client ID "abc.access" is mapped to the account "ci-bot"
    And "ci-bot" may view only "/acme/payments"
    When an MCP client calls /mcp with a valid Access JWT whose common_name is "abc.access" and no Authorization header
    Then the call runs as "ci-bot" with that account's library permissions

  Scenario: an explicit API token still wins over the Access assertion
    Given service token client ID "abc.access" is mapped to the account "ci-bot"
    When an MCP client calls /mcp with a valid Access JWT whose common_name is "abc.access" and a wrong API token
    Then /mcp answers 401

  Scenario Outline: an assertion that cannot be trusted is ignored
    Given service token client ID "abc.access" is mapped to the account "ci-bot"
    And an Access JWT that <problem>
    When it is sent to the session and to /mcp
    Then the session state is "signed_out" and /mcp answers 401

    Examples:
      | problem                              |
      | is signed by an unknown key          |
      | has another audience                 |
      | has another issuer                   |
      | has expired                          |
      | is not valid yet                     |
      | belongs to an unmapped service token |

  Scenario: the feature is off by default
    Given no Cloudflare Access settings
    When a request carries any Cf-Access-Jwt-Assertion header
    Then it is ignored and sign-in works as before
