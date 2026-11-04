Feature: First-run setup
  As the operator of a new instance
  I want it to offer nothing but the creation of its first admin
  So that an instance on a network port is never open to anyone

  Scenario: Everything but setup is refused before the first account exists
    Given a fresh instance
    When a client lists the libraries over the REST API
    Then the request is refused with "setup_required"

  Scenario: Creating the admin from the command line
    Given a fresh instance
    When the operator runs "exactdocs admin create" with the username "ada" and the password "correct horse battery staple"
    Then the admin "ada" can sign in with the password "correct horse battery staple"
    And the admin cannot sign in with the password "wrong horse battery staple"
    And the setup endpoint is no longer available

  Scenario: Creating the admin through the setup endpoint
    Given a fresh instance
    When a client sets the instance up with the username "ada" and the password "correct horse battery staple"
    Then the response status is 201
    And the admin "ada" can sign in with the password "correct horse battery staple"
    And the setup endpoint is no longer available

  Scenario: A password that is too short is refused and nothing is created
    Given a fresh instance
    When a client sets the instance up with the username "ada" and the password "short"
    Then the response status is 422
    And the instance still needs its setup
