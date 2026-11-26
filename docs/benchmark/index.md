# Benchmark

!!! abstract "TL;DR"
    - Three benchmarks (ingestion, retrieval, agent) run on the same [golden set](golden-set.md):
      321 questions about five projects at pinned versions.
    - The result tables are generated from the recorded runs, not typed by hand.
    - Each benchmark's *Every run* page lists every recorded run, back to the first, and sorts and
      filters it: [ingestion](ingestion/history.md), [retrieval](retrieval/history.md),
      [agent](agent/history.md), [comparison](comparison/history.md).
    - Hosted models are not measured yet; every recommendation so far is for no models or local
      models ([Recommended defaults](defaults.md)).

How ExactDocs is measured, on what data, with what results, and which configuration it
recommends because of them. The benchmarks of E13 (#344) run on real projects' documentation at
pinned versions, so a change to chunking, ranking or a model is measured against the same
questions as the last one.

| Page | What it holds |
|---|---|
| [Golden set](golden-set.md) | the projects, versions and question kinds, and how the cases were written and checked |
| [Method](method/index.md) | the metrics, how a default is chosen, what runs in CI, how to reproduce a run and refresh these pages |
| [Ingestion results](ingestion/index.md) | what the importer makes of the corpus under each chunking configuration |
| [Retrieval results](retrieval/index.md) | every retrieval configuration at every chunking, per question kind and project |
| [Agent results](agent/index.md) | the same agent answering the golden set with no docs, with the ExactDocs MCP tools and with Grounded Docs';<br/>accuracy, time and tokens per arm |
| [Comparison with other tools](comparison/index.md) | other documentation tools on the same golden set, scored from their text: Grounded Docs |
| [Recommended defaults](defaults.md) | the configuration to use with no models, local models and hosted models |

!!! info "Where the numbers come from"
    The tables on the result pages are generated from the recorded runs in
    [`packages/exactdocs/evals/results/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/results).
    The commands and the full reference are in [Retrieval evals](../evals/index.md).
