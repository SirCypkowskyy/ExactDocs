"""Coding-agent CLIs run headless with each documentation arm (#497).

- ``harness`` declares the ``Harness`` protocol (write the CLI's configuration, give the command
  that runs it headless, parse its transcript) and what a run needs (the model, the arm's MCP
  server, the prompt);
- ``claude_code``, ``codex``, ``gemini_cli`` and ``opencode`` are its adapters, each pinned to one
  release of its CLI (``releases`` installs them);
- ``transcript`` is what a parsed transcript holds (tool calls, MCP calls, tokens with and without
  the thinking, USD);
- ``gate`` is the only way out of a run's network (a proxy to the model provider's host, a forward
  to the arm's MCP server); ``container`` runs each CLI in its own container behind it;
- ``endpoints`` serves each arm's MCP server over HTTP (``agent_bench.servers``);
- ``jobs`` builds the prompts of the coding tasks (#496) and the golden questions (#495), and
  ``run`` runs every job and grades or judges it;
- ``report`` aggregates per harness, model and arm, with intervals and paired tests;
- ``cli`` is ``just harness-bench``.

See docs/evals/harnesses.md.
"""
