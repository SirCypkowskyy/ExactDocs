Feature: Failed sign-ins are throttled
  As the admin of an instance reachable from the network
  I want repeated wrong passwords to be slowed down
  So that nobody can guess my password online, nor keep the server busy hashing guesses

  Background:
    Given a fresh instance behind a reverse proxy
    And the admin "ada" was set up with the password "correct horse battery staple"

  Scenario Outline: Repeated wrong passwords from one address are slowed down, on both sign-ins
    When a client at "203.0.113.7" fails to sign in as "root" 5 times through <first>
    Then its next sign-in through <second> is refused as rate limited, with a time to wait
    And the admin can still sign in through <second> from "198.51.100.2"

    Examples:
      | first             | second            |
      | the web sign-in   | the CLI login     |
      | the CLI login     | the web sign-in   |

  Scenario: Repeated wrong passwords for one username are slowed down from any address
    When clients at 5 different addresses fail to sign in as "ada" through the web sign-in
    Then a sign-in as "ada" through the CLI login from "192.0.2.99" is refused as rate limited, with a time to wait
