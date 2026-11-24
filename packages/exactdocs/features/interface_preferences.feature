Feature: Interface preferences follow the person
  As someone who relies on interface preferences (contrast, text size, motion, font)
  I want them saved to my account
  So that every browser I sign in from applies them, without setting them again

  Background:
    Given a fresh instance
    And the admin "ada" was set up with the password "correct horse battery staple"
    And the admin is signed in to the UI

  Scenario: An account that never saved its preferences gets the defaults, marked as not saved
    When the admin reads their interface preferences
    Then they are the default preferences, not saved yet

  Scenario: The preferences a browser had before the first sign-in are saved to the account
    When the browser saves its dark theme, more contrast, text at 125 percent, underlined links and Polish
    Then the admin's interface preferences are the ones the browser saved

  Scenario: Saved preferences follow the person to another browser
    Given the admin saved a dark theme, more contrast, text at 125 percent, underlined links and Polish
    When the admin signs in from another browser and reads their interface preferences
    Then they are the preferences the admin saved

  Scenario: A changed preference is saved at once
    Given the admin saved a dark theme, more contrast, text at 125 percent, underlined links and Polish
    When the admin changes the text size to 150 percent
    Then the admin's interface preferences have text at 150 percent and the rest as saved

  Scenario Outline: The interface language follows the person like the other preferences
    Given the admin saved a dark theme, more contrast, text at 125 percent, underlined links and Polish
    When the admin switches the interface language to <language>
    And the admin signs in from another browser and reads their interface preferences
    Then they are the preferences the admin saved, in <language>

    Examples:
      | language              |
      | English               |
      | the system's language |

  Scenario: Library logos are shown until the person hides them, then stay hidden everywhere
    Given the admin saved a dark theme, more contrast, text at 125 percent, underlined links and Polish
    When the admin hides library logos
    And the admin signs in from another browser and reads their interface preferences
    Then they are the preferences the admin saved, with library logos hidden

  Scenario: An interface older than the leaderboard opt-in keeps the person's choice
    Given the admin saved a dark theme, more contrast, text at 125 percent, underlined links and Polish
    When the admin opts in to the people leaderboard
    And a browser with an interface older than the opt-in switches to English
    And the admin signs in from another browser and reads their interface preferences
    Then the admin is still opted in, with the rest as saved but in English

  Scenario: Each account has its own preferences
    Given the admin saved a dark theme, more contrast, text at 125 percent, underlined links and Polish
    And "bob" is signed in and has an API token
    Then bob's interface preferences are the defaults, with his session and with his API token
    When bob saves a light theme, a dyslexia-friendly font and English with his API token
    Then bob's interface preferences are the ones he saved
    And the admin's interface preferences are still the ones the admin saved

  Scenario Outline: Preferences the interface does not offer are refused
    Given the admin saved a dark theme, more contrast, text at 125 percent, underlined links and Polish
    When the admin saves preferences with <problem>
    Then the preferences are refused as invalid, naming "<field>"
    And the admin's interface preferences are still the ones the admin saved

    Examples:
      | problem                                        | field              |
      | an unknown setting                             | sparkles           |
      | a text size of 95 percent                      | text_scale         |
      | a theme it does not offer                      | theme              |
      | a language it does not offer                   | language           |
      | library logos neither shown nor hidden         | library_logos      |
      | a leaderboard opt-in neither given nor refused | leaderboard_opt_in |
      | a missing setting                              | font               |

  Scenario: Nobody's preferences are read or saved without signing in
    When a signed-out client reads interface preferences
    Then the request is refused as unauthenticated
    When a signed-out client saves interface preferences
    Then the request is refused as unauthenticated
