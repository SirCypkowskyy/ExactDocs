Feature: Images referenced by imported articles are served by ExactDocs
  As a reader of a private library, or of an instance without internet access
  I want the images of an article to come from ExactDocs at the imported commit
  So that diagrams render without asking the git host, and nothing unsafe reaches the browser

  Background:
    Given ExactDocs imports the fixture docs repository

  Scenario: A referenced image is served from ExactDocs
    When "docs/" of the fixture repository at "next" is imported
    Then the image "img/flow.png" of "/fixture/docs-repo/next" is served as "image/png"
    And the served image is exactly the file of the repository at "next"

  Scenario: An image inside the selected paths is imported with the articles
    When "docs/" of the fixture repository at "next" is imported
    Then the image "docs/assets/logo.png" of "/fixture/docs-repo/next" is served as "image/png"

  Scenario: An SVG is served so that it cannot run anything
    When "docs/" of the fixture repository at "next" is imported
    Then the image "docs/assets/flow.svg" of "/fixture/docs-repo/next" is served as "image/svg+xml"
    And the served image is a download that no script can run in

  Scenario: Images are not guessed by the browser or kept by shared caches
    When "docs/" of the fixture repository at "next" is imported
    Then the image "img/flow.png" of "/fixture/docs-repo/next" is served with the blob SHA as its ETag
    And the served image may not be sniffed or cached by a shared cache

  Scenario: An image the repository lacks is listed, not fatal
    When "docs/" of the fixture repository at "next" is imported
    Then the import succeeds
    And the job lists the image "docs/assets/gone.png" as skipped with the code "missing_image"
    And the image "docs/assets/gone.png" of "/fixture/docs-repo/next" is not found

  Scenario: Only the images of articles are served
    When "docs/" of the fixture repository at "next" is imported
    Then the image "docs/guide/diagrams.md" of "/fixture/docs-repo/next" is not found
    And the image "img/never-referenced.png" of "/fixture/docs-repo/next" is not found

  Scenario: A version without the image does not serve it
    Given "/fixture/docs-repo/v1.3.0" is imported
    Then the image "img/flow.png" of "/fixture/docs-repo/v1.3.0" is not found

  Scenario: An oversized image is skipped and listed
    Given ExactDocs imports the fixture docs repository with images limited to 60 bytes
    When "docs/" of the fixture repository at "next" is imported
    Then the import succeeds
    And the job lists the image "img/flow.png" as skipped with the code "too_large"
    And the image "img/flow.png" of "/fixture/docs-repo/next" is not found
