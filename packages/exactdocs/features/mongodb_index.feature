@integration @mongodb
Feature: MongoDB holds the search and vector indexes
  As an operator whose data lives in MongoDB (Atlas, or MongoDB with mongot)
  I want ExactDocs' chunks and vectors indexed and searched there, filtered to the asked version
  So that keyword, vector and hybrid search run on the cluster I already operate

  The database still keeps every chunk and vector; MongoDB holds a copy per version, searched with
  Atlas Search ($search) and Atlas Vector Search ($vectorSearch), hybrid with $rankFusion. The
  scenario needs a MongoDB with mongot (EXACTDOCS_TEST_MONGODB_URL): CI runs the pinned
  mongodb/mongodb-atlas-local image. The embedding endpoint is a fake gateway that hashes terms.

  Scenario: ExactDocs indexes into and searches MongoDB
    Given ExactDocs is configured with a MongoDB connection string, database and collection
    When MongoDB is sent "v1.3.0" and "v1.4.0" on import and "v1.4.0" once embedded
    Then the chunks and vectors are stored as MongoDB documents with library and version fields
    And keyword, vector and hybrid searches answer from MongoDB, filtered to the asked version
