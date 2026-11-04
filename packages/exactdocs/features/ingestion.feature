Feature: Safe article parsing
  As an AI coding agent
  I want article titles to be right and hidden instructions to be gone
  So that I can trust what I read from a doc repository

  Scenario: The article title follows front matter, then H1, then file name
    Given the article "guide/install.md":
      """
      ---
      title: Install ExactDocs
      ---
      # Getting started
      """
    And the article "guide/auth.md":
      """
      # Authentication
      """
    And the article "notes.md":
      """
      Just some notes.
      """
    When the articles are imported
    Then the title of "guide/install.md" is "Install ExactDocs"
    And the title of "guide/auth.md" is "Authentication"
    And the title of "notes.md" is "notes"

  Scenario: Hidden characters are removed on import
    Given the article "hidden.md" contains a zero-width space and a bidi override
    When the articles are imported
    Then the stored Markdown of "hidden.md" contains neither
    And the stored Markdown of "hidden.md" is otherwise identical to the source

  Scenario: Malformed front matter does not stop the import
    Given the article "broken.md":
      """
      ---
      title: [unclosed
      ---
      # Still here
      """
    When the articles are imported
    Then the title of "broken.md" is "Still here"
    And "broken.md" is listed with the problem "malformed front matter"

  Scenario: MDX components are kept as text
    Given the article "tabs.mdx":
      """
      import { Tabs } from '@site/components'

      <Tabs>npm i exactdocs</Tabs>
      """
    When the articles are imported
    Then the stored Markdown of "tabs.mdx" is identical to the source
