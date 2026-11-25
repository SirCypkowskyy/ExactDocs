# Benchmark

How ExactDocs is measured, on what data, with what results, and which configuration it
recommends because of them. The benchmarks of E13 (#344) run on real projects' documentation at
pinned versions, so a change to chunking, ranking or a model is measured against the same
questions as the last one.

| Page | What it holds |
|---|---|
| [Golden set](golden-set.md) | the projects, versions and question kinds, and how the cases were written and checked |
| [Method](method.md) | the metrics, how a default is chosen, what runs in CI, how to reproduce a run and refresh these pages |
| [Ingestion results](ingestion.md) | what the importer makes of the corpus under each chunking configuration |
| [Retrieval results](retrieval.md) | every retrieval configuration at every chunking, per question kind and project |
| [Agent results](agent.md) | the same agent answering the golden set with no docs and with the ExactDocs MCP tools: accuracy, time and tokens per arm |
| [Comparison with other tools](comparison.md) | other documentation tools on the same golden set, scored from their text: Grounded Docs |
| [Recommended defaults](defaults.md) | the configuration to use with no models, local models and hosted models |

The tables on the result pages are generated from the recorded runs in
[`packages/exactdocs/evals/results/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/results);
the commands and the full reference are in [Retrieval evals](../evals.md).
