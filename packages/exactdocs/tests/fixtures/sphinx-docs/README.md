# Fixture Sphinx documentation

A small, fictional Sphinx documentation set in reStructuredText ("Acme Store", an ORM and a test
runner), modelled on the layout and constructs of SQLAlchemy's `doc/build` and behave's `docs/`
(#435). The content is original. Only `doc/` is used: tests copy it into a branch of a private
copy of the fixture docs repository (`features/steps/restructuredtext_steps.py`), next to its
Markdown `docs/`, or read the files directly (`tests/ingestion/test_restructuredtext.py`).

| Need | Where |
|---|---|
| `conf.py` (source root, `highlight_language`); never executed | `doc/build/conf.py` |
| title with an overline, `toctree` (not indexed), `:doc:` | `doc/build/index.rst` |
| `=` / `-` / `~` / `^` adornments, labels, `:ref:` in the file and to another file | `doc/build/orm/session.rst` |
| `:class:` / `:meth:` / `:func:` / `:attr:`, `~` and `.` targets, `:term:`, substitutions | `doc/build/orm/session.rst` |
| `code-block`, `sourcecode`, `::` with the `conf.py` language, doctest | `doc/build/orm/session.rst` |
| `note`, `warning`, `seealso`, `versionadded`, `deprecated` | `doc/build/orm/session.rst` |
| grid table, simple table, `list-table` | `doc/build/orm/session.rst` |
| `include` (with a nested include), `literalinclude` with `:pyobject:` and `:lines:` | `doc/build/orm/session.rst`, `orm/_inc/`, `orm/examples/` |
| an unknown directive and an unknown role (kept as text, a problem) | `doc/build/orm/session.rst` (`tab-set`, `:paramref:`) |
| an include that cannot be read (a problem) | `doc/build/orm/session.rst` (`../../../outside/missing.rst`) |
| behave-style tutorial: `code-block:: gherkin`, numbered and definition lists, `:pypi:` | `doc/build/tutorial.rst` |
| a `.txt` article (imported only when a path names `.txt`) | `doc/build/changelog.txt` |
