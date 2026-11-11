Feature: Local models: hybrid search and reranking with no network at all
  As an operator of an air-gapped instance, or of docs that may not leave it
  I want the embedding model and the reranker to run inside ExactDocs, from files on disk
  So that semantic search and reranking work without sending anything anywhere, and nothing is
  ever downloaded at run time

  The models here are tiny stand-ins built by the test (a bag-of-words embedding model and a
  word-overlap cross-encoder), run by the real fastembed and ONNX Runtime from the models
  directory, exactly as `exactdocs models pull` leaves models there. The defaults
  (BAAI/bge-small-en-v1.5 and Xenova/ms-marco-MiniLM-L-6-v2) run in CI's local-models eval job.
  Hybrid is chosen by the operator: it is no default until the eval suite says so (docs/evals.md).

  Background:
    Given ExactDocs is running with the fixture docs repository imported at "v1.3.0" and "v1.4.0"

  Scenario: Hybrid and rerank without any network
    Given ExactDocs is installed with the "local" extra and its models were pulled into the models directory
    And the embedding role is "local:exactdocs-test/tiny-embedding" and the reranker role is "local:exactdocs-test/tiny-reranker"
    And the process has no network access
    When "v1.4.0" is embedded and an agent searches "how do I retry failed calls"
    Then the result says retrieval mode "hybrid" and "reranked: true"
    And nothing tried to reach the network

  Scenario: A missing model is an error at start, not a download
    Given the embedding role is "local:BAAI/bge-small-en-v1.5" and the model is not in the models directory
    And the process has no network access
    When ExactDocs starts
    Then it refuses to enable the role with a message naming "exactdocs models pull"
    And it opens no connection to the Hugging Face Hub
