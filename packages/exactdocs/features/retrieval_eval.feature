Feature: A retrieval eval suite compares modes on the fixture libraries
  As a maintainer deciding which retrieval mode becomes a default
  I want recall, wrong-version rate, cost and latency per mode, measured the same way every time
  So that "hybrid is better" is a number, and one wrong-version result never slips through

  Scenario: The suite reports per-mode metrics
    When the eval suite runs with only BM25 available
    Then it reports recall@k, wrong-version rate, cost and latency for "bm25"
    And the modes that need a model are reported as unavailable, with the role they lack

  Scenario: A wrong-version result fails the suite
    Given a mode returns one chunk of "v2.0.0" for a question pinned to "v1.4.0"
    When the eval suite runs
    Then it fails, whatever the recall

  Scenario: A changed dataset resets the baseline instead of failing
    Given develop's baseline was recorded for dataset fingerprint "A"
    And the branch changes the dataset to fingerprint "B" and stores a new baseline for "B"
    When the eval runs in CI
    Then the drop gate and the ratchet compare against the branch's baseline for "B"
    And the summary says the baseline was reset because the dataset changed

  Scenario: An unchanged dataset keeps the ratchet
    Given develop's baseline and the branch use the same dataset fingerprint
    When the branch stores a lower recall@5
    Then CI fails with "the baseline only moves up"
