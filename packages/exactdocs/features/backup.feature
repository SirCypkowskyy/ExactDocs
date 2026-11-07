Feature: Backup and restore
  As the operator of an instance the team depends on
  I want to back it up while it serves and restore it with one command each
  So that a lost disk or a move to another host costs minutes, not a re-import

  Scenario: Backup and restore round-trip
    Given an instance with libraries, versions, settings, accounts and tokens
    When the operator runs "exactdocs backup" and restores it into an empty data dir
    Then the restored instance serves the same libraries and accepts the same tokens

  Scenario: A backup from a newer release is refused
    Given a backup taken by a newer release of ExactDocs
    When the operator restores it into an empty data dir
    Then the restore is refused, naming the newer schema
    And nothing was written to the data dir

  Scenario: Restore never overwrites an instance
    Given an instance with libraries, versions, settings, accounts and tokens
    When the operator restores a backup into that instance's data dir
    Then the restore is refused because the data dir already holds a database
