Feature: Access log
  As a library owner or an operator
  I want a log of access changes and deletions
  So that we know who shared or deleted what, and when

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: A grant is recorded
    Given "alice" is an admin of "/fixture/docs-repo"
    When "alice" grants "bob" the viewer role on "/fixture/docs-repo"
    Then the library's audit log shows actor "alice", the grant and the time

  Scenario: Role changes and revocations are recorded, newest first, for library admins only
    Given "alice" is an admin of "/fixture/docs-repo"
    When "alice" grants "bob" the viewer role on "/fixture/docs-repo"
    And "alice" grants "bob" the contributor role on "/fixture/docs-repo"
    And "alice" takes the role of "bob" on "/fixture/docs-repo" away
    Then "alice" reads in the audit log of "/fixture/docs-repo", newest first:
      | actor | change  | subject | role        | previous role |
      | alice | revoked | bob     | contributor |               |
      | alice | granted | bob     | contributor | viewer        |
      | alice | granted | bob     | viewer      |               |
      | admin | granted | alice   | admin       |               |
    And "carol", a viewer of "/fixture/docs-repo", asking for its audit log is refused

  Scenario: An ownership transfer is recorded, and the previous owner's new admin role with it
    Given "alice" is the creator of "/fixture/docs-repo"
    And "carol" is an admin of "/fixture/docs-repo"
    When the creator transfers "/fixture/docs-repo" to "carol"
    Then the library's audit log shows actor "alice", the ownership transfer to "carol" and the time
    And "carol" reads in the audit log of "/fixture/docs-repo", newest first:
      | actor | change                | subject | role    | previous role |
      | alice | ownership_transferred | carol   | creator | admin         |
      | alice | granted               | alice   | admin   | creator       |
      | admin | granted               | carol   | admin   |               |

  Scenario: A deleted library stays in the operator's access log
    Given "bob" is a viewer of "/fixture/docs-repo"
    When the operator removes the library "/fixture/docs-repo"
    Then the operator's access log shows that "admin" deleted "/fixture/docs-repo"
