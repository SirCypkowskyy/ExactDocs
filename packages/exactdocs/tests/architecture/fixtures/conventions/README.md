Fixtures for `test_conventions.py`: source files the convention checker reads, never imports.
They break the rules on purpose and are excluded from ruff and ty. A bad fixture marks each
line the checker must report with `# expect: <rule>`.
