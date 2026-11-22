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

  Scenario: A deleted library stays in the operator's access log
    Given "bob" is a viewer of "/fixture/docs-repo"
    When the operator removes the library "/fixture/docs-repo"
    Then the operator's access log shows that "admin" deleted "/fixture/docs-repo"
