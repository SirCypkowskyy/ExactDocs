"""The agent benchmark (#348): an agent with only the ExactDocs MCP tools answers the golden set.

``harness`` starts ExactDocs as shipped (``exactdocs serve --stdio``) over the imported golden
corpus and records what a pydantic-ai agent does with its MCP tools; ``judge`` grades each answer
with an LLM; ``report`` aggregates; ``agreement`` compares the judge with hand labels; ``offline``
holds the stand-in models the harness is tested with. See docs/evals.md#the-agent-benchmark.
"""
