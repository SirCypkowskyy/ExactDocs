Feature: Cancelling queued and running jobs
  As the operator or a contributor of a library
  I want to stop an import or an embedding run that I no longer want
  So that a wrong import or a costly embedding does not have to run to its end

  Scenario: Cancelling a running embedding job keeps what it finished
    Given ExactDocs embeds the fixture docs repository at "v1.4.0" in batches of 2 chunks
    And its embedding job is running a batch
    When the operator cancels the embedding job
    Then the answer shows the job is being cancelled by "admin"
    And once the batch in flight ends, no other batch is sent to the provider
    And the embedding job ends "cancelled" by "admin" with the vectors of that batch kept

  Scenario: A cancelled embedding resumes from the chunks still missing
    Given ExactDocs embeds the fixture docs repository at "v1.4.0" in batches of 2 chunks
    And its embedding job was cancelled after one batch
    When the operator queues the embedding of the library again
    Then the new embedding job succeeds
    And no chunk was sent to the provider twice

  Scenario: Cancelling a queued import
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And an import of "v9.9.9" of "/fixture/docs-repo" is queued
    When the operator cancels that job
    Then the response status is 200
    And the job is "cancelled" by "admin"
    And when the worker picks the job up, it never starts
    And "/fixture/docs-repo" has no version "v9.9.9"

  Scenario: Cancelling needs the contributor role
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And an import of "v9.9.9" of "/fixture/docs-repo" is queued
    And "bob" is a viewer of "/fixture/docs-repo"
    When "bob" cancels that job
    Then the response status is 403
    And the error code is "forbidden"

  Scenario: A finished job cannot be cancelled
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And an import of "v9.9.9" of "/fixture/docs-repo" that already failed
    When the operator cancels that job
    Then the response status is 409
    And the refusal says the job is already "failed"

  Scenario: Cancelling a job twice
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"
    And an import of "v9.9.9" of "/fixture/docs-repo" is queued
    When the operator cancels that job
    And the operator cancels that job
    Then the response status is 409
    And the refusal says the job is already "cancelled"
