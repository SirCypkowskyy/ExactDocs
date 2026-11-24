# Method

Three benchmarks run on the [golden set](golden-set.md), each over every pinned version:

- the **ingestion benchmark** (#346) imports the corpus under each chunking configuration and
  measures the chunks against the source;
- the **retrieval benchmark** (#347) asks every question through `search_docs` in every retrieval
  configuration at every chunking, and names a default per budget;
- the **agent benchmark** (#348) starts ExactDocs as shipped and lets an agent whose only tools
  are the ExactDocs MCP tools answer the questions; an LLM judge grades the answers.

Their full reference (every flag, field and rule) is in [Retrieval evals](../evals.md). This page
gives the definitions the result pages rely on.

## Chunking configurations

| Name | Settings | What it does |
|---|---|---|
| `default` | split level 3, `max_chars` 4,000 | today's default (#381): `#` to `###` start a chunk; a longer one is cut again at deeper headings |
| `h6` | split level 6, no merging, no bound | every heading starts a chunk (the default before #381) |
| `h2` | split level 2, no bound | only `#` and `##` start a chunk; deeper sections stay inside their parent |
| `merge-400` | split level 6, `min_chars` 400, `max_chars` 4,000 | every heading starts a chunk, then a chunk under 400 characters is merged with the next while the result stays within 4,000 |

`default` is what a new library gets, so it follows the shipped default; until #381 it was
`h6`, and the recorded runs took the new names when it changed.

The golden set names sections as `h6` cuts them: every heading. A configuration that cuts
coarser or finer would lose every hit to a heading path that no longer exists, so a returned chunk of the right
version and article answers an expected section when its heading path is the expected one, when
it is a section inside the expected one (a finer cut), or when it is a parent of the expected one
and holds its heading (a coarser cut). The ingestion results also show recall@5 with exact paths
only, for comparison.

## Retrieval metrics

Answerable cases are the 267 cases that name sections; unanswerable cases are the other 54.

| Metric | Over | Definition |
|---|---|---|
| recall@k (k = 1, 5, 10) | answerable cases | share of cases whose first expected section is in the top k results |
| section recall@k (k = 5, 10) | answerable cases | per case, the share of its expected sections in the top k, each counted once; averaged over cases. Equal to recall@k for a case with one section, lower when a `cross-page` answer comes back only in part |
| MRR | answerable cases | mean of 1 / the rank of the first expected section; 0 when it is not in the top 10 |
| nDCG@10 | answerable cases | binary relevance: a hit at rank *i* scores 1 when it answers an expected section no earlier hit answered, else 0. DCG@10 = Σ *rel*<sub>i</sub> / log<sub>2</sub>(*i* + 1) over the top 10, divided by the ideal DCG, which puts every expected section first |
| wrong-version rate | every case | share of cases with any result of another version, read back by chunk ID; it must be 0, and a configuration with one is never recommended |
| unanswerable clean | unanswerable cases | share that returned nothing of another version |
| no answer | unanswerable cases | share that came back with no result at all, the only "no answer" signal `search_docs` has |
| answerable empty | answerable cases | share that came back with no result, a wrong "no answer" |
| p50 / p95 latency | every case | nearest-rank percentiles of the search alone, one question at a time, on the machine the run names |
| tokens / USD per question | every case | what the spend ledger grew by during each search (embedding a query, a judgment, a HyDE answer, an agent run); USD from the configured prices or `genai-prices` |
| index | per embedding model and chunking | seconds, tokens and USD of embedding the whole corpus once |

recall@k and MRR count the first expected section only, as the fixture eval suite does, so their
numbers stay comparable across the three benchmarks; section recall and nDCG@10 count every
expected section.

## Intervals and significance

The golden set has a few hundred cases, so a difference of a few points between two
configurations can be noise. Every number a benchmark reports is a mean over cases (a rate is the
mean of a hit or a miss), and each comes with a 95% interval, and each comparison with a paired
test (#489). The code is `packages/exactdocs/evals/retrieval_eval/stats.py`.

- **Intervals**: a percentile bootstrap over the cases. 10,000 times, the cases are drawn again
  with replacement (as many as there are) and the metric recomputed; the interval runs from the
  2.5th to the 97.5th percentile of those values. The draws come from Python's
  `random.Random(489)` and depend only on the seed and the number of cases, so every
  configuration that answered the same cases is resampled with the same draws (a paired
  bootstrap), and a rerun gives the same intervals. The report records the seed, the number of
  resamples, the confidence and the significance level (`statistics`). A rate that is the same
  for every case (a wrong-version rate of 0) gets an interval of no width; the bootstrap cannot
  say more than the cases do.
- **Hit-or-miss outcomes** (recall@k, agent accuracy): McNemar's test on the cases where the two
  configurations disagree, in its mid-p version. With *n* disagreements and *k* the smaller of
  "only A found it" and "only B found it", the p-value is 2 P(X < *k*) + P(X = *k*) for X ~
  Binomial(*n*, ½): the exact test counts P(X = *k*) twice and is conservative, the mid-p version
  keeps close to the nominal level (Fagerland, Lydersen and Laake, 2013).
- **Graded outcomes** (MRR, nDCG@10): a paired sign-flip permutation test. Under no difference,
  each case's difference is as likely to have either sign; 10,000 random sign patterns (same
  seed) give the p-value, the share of patterns whose mean difference is at least as far from 0
  as the observed one (counting the observed one). This is the randomization test Smucker, Allan
  and Carterette (2007) recommend for comparing retrieval systems.
- Each test also gives the difference with its paired bootstrap interval. A difference is
  **significant** when its p-value is under 5%.

Each result of the retrieval benchmark is tested against its budget's default, on the
answerable cases both answered; the table is under *Against the budget's default* on
[Retrieval results](retrieval.md). In the agent benchmark each agent model's accuracy under a
retrieval configuration is tested against its accuracy under the run's first configuration.

**Small groups are wide.** A question kind or a project holds about 50 cases, a fifth of the
answerable ones, so its intervals are about twice as wide as the whole set's: at 80% recall,
roughly ±11 points against ±5. Differences per kind or per project of a few points say little.

A result can be tested only when the report kept every case's outcome (`rows`). Every result of
the recorded retrieval run does (it was recorded again for #490).

## Scoring tools that return text

ExactDocs' results are scored by their chunk IDs. Tools that return text (Context7, Grounded
Docs, a grep or fixed-window baseline) are scored from the text alone, with the same metrics. Each
pinned version's articles are cut at every heading with the importer's own parser and chunker,
and texts are compared as sets of 5-word shingles after dropping markup, link targets and case. A
result answers a section when it holds at least 80% of the section's own text, or when at least
80% of the result lies in the section with its subsections; it is of the right version, of
another version, version-neutral (the text is the same in both) or unmatched by the versions
whose sections it matches. Besides the retrieval metrics, a tool scored from text is reported
with the share of version-neutral and unmatched results, the tokens of context it returned per
question (characters / 4) and up to its first hit, and the share of the case's facts its text
holds.

The scorer was calibrated on ExactDocs' own BM25 results for the whole golden set, scored both
ways: at the `default` chunking it takes 99.5% of the hit and miss decisions (each expected
section's rank in the top 10, or a miss) as chunk-ID scoring does, against a criterion of 98%.
The threshold, the sweep that chose it and every disagreement are in
[Scoring text results](../evals.md#scoring-text-results).
[Comparison with other tools](comparison.md) scores other tools with it.

## Ingestion metrics

Coverage is the share of the golden set's expected sections that start a chunk (a section held
inside a bigger chunk is "held", not covered). Next to it: cuts inside fenced code, tables and
lists; source characters that end up in no chunk; chunk sizes in estimated tokens (characters /
4) at p50, p95 and maximum; the share of chunks under 50 tokens; chunks holding more than one
top-level heading; empty or wrong heading paths; headings the chunks miss or invent; and
MkDocs-specific losses. The definitions are in
[The ingestion benchmark](../evals.md#the-ingestion-benchmark).

## Agent metrics and the judge

The judge is an LLM given the question, version, kind, reference answer, facts and the agent's
answer (not the docs). It grades `correct` (every fact, nothing contradicted),
`partially_correct` (some facts, nothing contradicted), `wrong` (no fact, a contradiction or an
invented API) or `refused` (says the docs do not cover it). Accuracy is the share `correct`,
plus `refused` on `unanswerable` cases, where refusing is the right answer. The report also
counts answers true only of another version, how often the agent read every section the case
names in full, and whether it read another version, with tool calls, tokens, USD and wall time
per question.

**Judge agreement with hand labels: not measured yet.** The judge is checked by labelling at
least 50 answers of a real-model run by hand and comparing (`just agent-bench sample`, then
`just agent-bench agreement`; see [Judge agreement](../evals.md#judge-agreement)). No real-model
run exists yet, so neither does the agreement rate.

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
   significance](#intervals-and-significance)). Otherwise the cheaper default stays, and the
   reason says which it missed: how far the dearer one fell short of the margin, or its p-value.
   A dearer configuration recorded without its per-case outcomes cannot be tested, so it does not
   become a default either.

A budget nothing of which ran is "not measured yet". The margin and the test apply between
budgets; between chunkings of one budget the best one wins outright.

## What runs where

| Run | Where | Models |
|---|---|---|
| quick tests of all three benchmarks and the text scorer | every pull request (`uv run pytest`, `uv run behave`) | stand-ins only, tiny local corpora |
| `just golden-validate` rules | every pull request (pytest) | none |
| ingestion benchmark `--check` | every release, *Retrieval eval* job | none |
| retrieval benchmark, BM25 at `default`, `--check` | every release, *Retrieval eval* job | none |
| retrieval benchmark with local models | by hand (`just retrieval-bench --offline`) | local, pulled with `exactdocs models pull` |
| retrieval benchmark, hosted configurations | by hand: the manual *Retrieval eval (real providers)* workflow (`eval-providers.yml`) with the `benchmark` input ticked | hosted |
| text scorer calibration | by hand (`just text-bench --offline`), when the matcher or the chunker changes | none |
| Grounded Docs on the golden set | by hand (`just grounded-bench --offline`), or the manual *Grounded Docs benchmark* workflow (`grounded-bench.yml`); quick tests replay recorded responses on every pull request | local, `BAAI/bge-small-en-v1.5` pulled with `exactdocs models pull` |
| agent benchmark | by hand: the manual *Agent benchmark (real providers)* workflow (`agent-bench.yml`), or `just agent-bench run` locally | hosted |

No CI or release run calls a hosted model or needs a secret.

## Reproducing a run

Each JSON report records what a rerun needs. `retrieval.json` holds the golden set's
fingerprint, every pinned commit, the ExactDocs commit, the machine, the library versions, each
model with its Hub revision, the AI settings of each configuration, every case's outcome, and
the seed and resamples of the intervals
([Reproducing a result](../evals.md#reproducing-a-result)). The commands:

```bash
just ingestion-bench --offline --out packages/exactdocs/evals/results
EXACTDOCS_MODELS_DIR=~/.cache/exactdocs/models just retrieval-bench --offline \
  --configs 'bm25,hybrid:bge-small-en-v1.5,bm25+ce@h6,bm25+ce@h2,bm25+ce@default,hybrid:bge-small-en-v1.5+ce@h6,hybrid:bge-small-en-v1.5+ce@default,hybrid:snowflake-arctic-embed-s@h6' \
  --out packages/exactdocs/evals/results
```

The second is the recorded retrieval run ([The recorded run](../evals.md#the-recorded-run)): 3 h
17 min on a 4-CPU runner, most of it embedding the corpus and the cross-encoder.

## Refreshing these pages

The tables on the benchmark pages are not typed by hand. Each page holds generated blocks between
`<!-- bench:<name> -->` and `<!-- /bench -->` markers, and `just bench-pages` refills them from
`packages/exactdocs/evals/results/ingestion.json`, `retrieval.json`, `grounded-docs.json` and the
golden set, with the benchmarks' own Markdown renderers. Everything outside the markers is prose.

```bash
just bench-pages            # rewrite the blocks after a new recorded run
just bench-pages --check    # fail when a page differs from the reports
```

A pull request test runs the check, so a recorded run or a golden-set change that does not
refresh the pages fails CI. The prose around the tables (the findings on
[Recommended defaults](defaults.md), the run dates) is updated by hand in the same pull request.
