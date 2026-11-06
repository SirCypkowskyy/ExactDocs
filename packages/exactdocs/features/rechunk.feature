Feature: A re-chunk cuts every article exactly as its import did
  As a documentation maintainer who changes a library's chunking
  I want each article re-cut as an import with the new chunking would cut it
  So that no section disappears from search depending on which job cut it first

  Background:
    Given ExactDocs imports the fixture docs repository
    And the fixture repository is a private copy

  Scenario: A comment-only front matter followed by a second, invalid "---" block
    Given a commit on branch "next" adds "docs/odd.md" with a comment-only front matter and then an invalid "---" block holding the heading "Quokka habits"
    And "/fixture/docs-repo/next" is imported
    And searching "quokka" in "next" finds the section "Quokka habits" of "docs/odd.md"
    When the user sets the split level to "h1"
    Then the re-chunking job succeeds
    And searching "quokka" in "next" finds the section "Quokka habits" of "docs/odd.md"
    And the job has no note on "docs/odd.md"
