Feature: Sphinx documentation in reStructuredText imports like Markdown
  As an operator adding a Python library documented with Sphinx (SQLAlchemy, behave, ...)
  I want its reStructuredText articles imported with their headings, code, tables and admonitions
  So that agents search, outline and read them as they do Markdown articles

  Background:
    Given ExactDocs imports the fixture docs repository
    And the fixture repository is a private copy
    And a branch "sphinx" adds the fixture Sphinx documentation

  Scenario: A Sphinx documentation set imports like Markdown
    When "sphinx" is added with the paths "doc/build/" excluding ""
    Then every reStructuredText article of the Sphinx documentation is an article of "sphinx"
    And the article "doc/build/orm/session.rst" of "sphinx" is titled "Using a Store"
    And its outline lists "Using a Store", "Opening a Store", "Retry policies", "Flush order", "Including shared text" and "Reference", in that order
    And a search of "sphinx" for "retry_on" finds the section "Using a Store > Opening a Store > Retry policies" of "doc/build/orm/session.rst"
    And reading that section gives its "python+sql" code block and its tables

  Scenario: Sphinx constructs are handled, not dumped as text
    When "sphinx" is added with the paths "doc/build/" excluding ""
    Then the article "doc/build/orm/session.rst" of "sphinx" reads as Markdown:
      | what                            | text                                                |
      | a code block keeps its language | ```python+sql                                       |
      | an include is expanded          | The pool keeps at most `pool_size` connections open. |
      | a literalinclude is code        | def open_and_add(order):                            |
      | an admonition is an admonition  | > [!WARNING]                                        |
      | a reference in the file a link  | [Opening a Store](#opening-a-store)                 |
      | a class reference is code       | `acme.engine.Engine`                                |
      | a method reference is code      | `flush()`                                           |
      | a substitution is replaced      | The `Store` is where                                |
    And the article "doc/build/index.rst" of "sphinx" does not contain "toctreeonlyentry"
    And the job lists "doc/build/orm/session.rst" as imported with a markup problem naming "tab-set" and "paramref"
    And no file of "sphinx" failed the import

  Scenario: A mixed repository
    When "sphinx" is added with the paths "docs/guide/, doc/build/" excluding ""
    Then "sphinx" has the article "docs/guide/install.md"
    And "sphinx" has the article "doc/build/tutorial.rst"
    And a search of "sphinx" for "gherkin checkout" finds an article below "doc/build/"
