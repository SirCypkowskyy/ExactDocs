@redis
Feature: Redis holds the search and vector indexes
  As an operator who runs Redis 8 (its Query Engine)
  I want ExactDocs' chunks and vectors indexed and searched there, filtered to the asked version
  So that keyword, vector and hybrid search run on the Redis I already operate

  The database still keeps every chunk and vector; Redis holds a copy per version. The scenario
  needs a Redis 8 server (EXACTDOCS_TEST_REDIS_URL, and EXACTDOCS_TEST_REDIS_PASSWORD when it
  takes one): CI runs the pinned redis image. The embedding endpoint is a fake gateway that
  hashes terms.

  Scenario: ExactDocs indexes into and searches Redis
    Given ExactDocs is configured with a Redis URL and an index prefix, with native hybrid search
    When "v1.3.0" and "v1.4.0" are imported and "v1.4.0" is embedded
    Then its chunks and vectors are stored as hashes with library and version TAG fields
    And keyword, vector and hybrid searches answer from Redis, filtered to the asked version
