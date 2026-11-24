Feature: People link their account to Discord, Google, Microsoft or any OAuth provider
  As a person who already has an ExactDocs account
  I want to attach the identity providers I use to it, each shown with its own icon
  So that I sign in the way I like, without a second account

  Scenario: a person links a provider to their account
    Given the server has Google configured and a person is signed in with a local account
    When they choose "Link Google" in Account settings and complete Google's sign-in
    Then their account lists Google as linked
    And they can sign in with Google from then on

  Scenario: unlinking
    Given the server has Google configured and a person is signed in with a local account
    And they linked Google to their account
    When they unlink Google after confirming
    Then Google no longer signs them in
    And they keep their password to sign in with

  Scenario: the last way to sign in is never unlinked
    Given sign-in provider "corp" of kind "oidc" with issuer "https://idp.example.com"
    And a person who only signs in through "corp"
    When they try to unlink "corp"
    Then the unlink is refused with "last_sign_in_method"
    And "corp" still signs them in

  Scenario: an identity already linked to another account is refused
    Given the server has Google configured and a person is signed in with a local account
    And another person linked their Google identity to their own account
    When the person links that same Google identity
    Then they are back in Account settings with the link refused as "identity_linked_elsewhere"
    And that Google identity still signs the other person in

  Scenario: a preset creates no accounts, it only signs in linked identities
    Given the server has Google configured and a person is signed in with a local account
    When someone signs in with a Google identity nobody linked
    Then the external sign-in is refused with "not_linked"
    And no session is created

  Scenario Outline: presets need only the client, and show their own icon
    Given an operator configures <kind> with only its client ID and secret
    Then the sign-in page and Account settings show "<name>" with the built-in "<icon>" icon

    Examples:
      | kind      | name      | icon      |
      | discord   | Discord   | discord   |
      | google    | Google    | google    |
      | microsoft | Microsoft | microsoft |

  Scenario: a generic provider shows the operator's icon, served by ExactDocs
    Given an operator configures a generic OIDC provider with an icon file of their own
    Then the sign-in page and Account settings show its icon from ExactDocs' own origin
    And the icon is sanitised and may be cached
    And an icon file that is not a small PNG, WebP or SVG stops the server at start
