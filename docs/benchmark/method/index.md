# Method

!!! abstract "TL;DR"
    - Covers the three benchmarks' metrics, the statistics, how a default is chosen, what runs where,
      and how to reproduce a run and refresh these pages.
    - Every reported number has a 95% bootstrap interval, and every comparison a paired test;
      a difference is significant when p is under 5%.
    - A dearer budget gets its own default only with at least 5 points more recall@5 **and** a
      significant difference.
    - No CI or release run calls a hosted model or needs a secret.

Three benchmarks run on the [golden set](../golden-set.md), each over every pinned version:

- the **ingestion benchmark** (#346) imports the corpus under each chunking configuration and
  measures the chunks against the source;
- the **retrieval benchmark** (#347) asks every question through `search_docs` in every retrieval
  configuration at every chunking, and names a default per budget;
- the **agent benchmark** (#348) starts ExactDocs as shipped and lets an agent whose only tools
  are the ExactDocs MCP tools answer the questions; an LLM judge grades the answers.

Their full reference (every flag, field and rule) is in [Retrieval evals](../../evals/index.md). This page
and the two below give the definitions the result pages rely on.

## Which page do I need

| Page | What it holds |
|---|---|
| [Metrics and statistics](metrics.md) | the retrieval, text, ingestion and agent metrics, the intervals and the tests |
| [Running and refreshing](runs.md) | what runs where, reproducing a run, the coding tasks, refreshing these pages |

## Chunking configurations

| Name | Settings | What it does |
|---|---|---|
| `default` | split level 3, `max_chars` 4,000 | today's default (#381): `#` to `###` start a chunk; a longer one is cut again at deeper headings |
| `h6` | split level 6, no merging, no bound | every heading starts a chunk (the default before #381) |
| `h2` | split level 2, no bound | only `#` and `##` start a chunk; deeper sections stay inside their parent |
| `merge-400` | split level 6, `min_chars` 400, `max_chars` 4,000 | every heading starts a chunk;<br/>a chunk under 400 characters is then merged with the next while the result stays within 4,000 |

`default` is what a new library gets, so it follows the shipped default. Until #381 it was `h6`,
and the recorded runs took the new names when it changed.

The golden set names sections as `h6` cuts them: every heading. A configuration that cuts coarser
or finer would lose every hit to a heading path that no longer exists, so a returned chunk of the
right version and article answers an expected section when:

- its heading path is the expected one;
- it is a section inside the expected one (a finer cut);
- or the chunk holds the expected section's heading.

What a chunk holds is what the chunker recorded for it, read by chunk ID (#503). All of these
count:

| Chunking | How the expected section ends up in the chunk |
|---|---|
| `h2` | kept inside its parent |
| `default` | kept with a sibling when a long section is cut again at 4,000 characters |
| `merge-400` | merged with its neighbours |

The ingestion results also show recall@5 with exact paths only, for comparison.

## How a default is chosen

The retrieval benchmark names a default for each budget, cheapest first: `none` (no model),
`local` (models that run on the instance) and `hosted` (models behind a provider). For each
budget:

1. The candidates are the configurations of that budget that ran with no result of another
   version, no read outside the version, no error and no reranker fallback.
2. The best candidate is the one with the highest recall@5, then nDCG@10, then MRR, then the lower
   USD per question, then the lower p95 latency. Every chunking counts, so the best chunking is
   chosen with the configuration.
3. It becomes the budget's default only when its recall@5 beats the cheaper budget's default by
   **at least 5 points** (`DEFAULT_MARGIN_POINTS`, the same margin the eval suite asks of any new
   default mode) **and** the difference is **significant**: McNemar's test (mid-p) of the two on
   the same cases gives a p-value under 5% ([Intervals and
   significance](metrics.md#intervals-and-significance)). Otherwise the cheaper default stays, and the
   reason says which it missed: how far the dearer one fell short of the margin, or its p-value.
   A dearer configuration recorded without its per-case outcomes cannot be tested, so it does not
   become a default either.

A budget nothing of which ran is "not measured yet". The margin and the test apply between
budgets; between chunkings of one budget the best one wins outright.
