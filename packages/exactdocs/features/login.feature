Feature: Admin session
  As the admin of an instance
  I want to sign in to the web UI with a session that expires and cannot be stolen by script
  So that only I can use the instance from a browser

  Background:
    Given a fresh instance
    And the admin "ada" was set up with the password "correct horse battery staple"

  Scenario: Signing in and out
    Then the libraries are not reachable
    When the admin signs in with the password "correct horse battery staple"
    Then the UI session is active for "ada"
    And the session cookie is HttpOnly and SameSite=Lax
    And the libraries are reachable
    When the admin signs out
    Then the libraries are no longer reachable with that session
    And the UI session is not active

  Scenario: A wrong password and an unknown user are told apart by nobody
    When the admin signs in with the password "wrong horse battery staple"
    Then the sign-in is refused with "invalid_credentials"
    When "nobody" signs in with the password "correct horse battery staple"
    Then the sign-in is refused with "invalid_credentials"
    And no session cookie was set

  Scenario: A session cookie never authenticates MCP
    Given the admin is signed in to the UI
    When the browser calls the MCP endpoint with the session cookie only
    Then the MCP endpoint treats the call exactly like one without the cookie

  Scenario: Another site cannot sign the admin in or out
    Given the admin is signed in to the UI
    When a page on "https://evil.example" signs the admin out
    Then the request is forbidden
    And the libraries are reachable
    When a page on "https://evil.example" signs in with the password "correct horse battery staple"
    Then the request is forbidden

  Scenario: Resetting the password signs the admin out everywhere
    Given the admin is signed in to the UI
    When the operator runs "exactdocs admin reset-password" with the username "ada" and the password "a brand new passphrase"
    Then the libraries are no longer reachable with that session
    When the admin signs in with the password "correct horse battery staple"
    Then the sign-in is refused with "invalid_credentials"
    When the admin signs in with the password "a brand new passphrase"
    Then the UI session is active for "ada"
