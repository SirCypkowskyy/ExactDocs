"""The agent benchmark (#348, #495): an agent answers the golden set with each documentation arm.

``arms`` declares the arms (``none``: no tools; ``exactdocs``: ExactDocs as shipped; ``context7``
and ``grounded-docs`` to follow) and keeps the judge blind to them; ``harness`` starts ExactDocs as
shipped (``exactdocs serve --stdio``) over the imported golden corpus and records what a
pydantic-ai agent does and spends (tokens, thinking, wall time, retries); ``models`` resolves the
agent and judge models (stand-ins, Ollama with retries); ``judge`` grades each answer with an LLM;
``report`` aggregates and compares the arms; ``agreement`` compares the judge with hand labels;
``offline`` holds the stand-in models; ``redact`` keeps credentials out of the report. See
docs/evals.md#the-agent-benchmark.
"""
