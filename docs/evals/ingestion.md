# The ingestion benchmark

!!! abstract "TL;DR"
    - Retrieval can only return what ingestion produced. The ingestion benchmark (#346) measures
      what the importer makes of the golden corpus under four chunking configurations, and the
      BM25 recall each one leads to.
    - It needs no model and takes about a minute per configuration.
    - The manual *Eval* workflow runs it with `--check` against the recorded run: coverage may
      not drop, the integrity counts may not rise, and BM25 recall@5 may not drop more than 2
      points.
    - A hit counts when the returned chunk holds the expected heading, so a coarser or finer cut is
      not penalised (#503).

```bash
just ingestion-bench --offline                      # every configuration, every project
just ingestion-bench --configs default,h2 --projects zod
just ingestion-bench --out packages/exactdocs/evals/results   # refresh the recorded run
just ingestion-bench --offline --check              # fail when something got worse than the recorded run
```

For each configuration it:

1. imports every pinned version with the real importer into its own model-free instance (the same
   path as `golden-import`, with the library's chunking settings set first);
2. reads back the chunks the importer stored, and compares them with the source at the pinned
   commit;
3. runs the whole golden set through BM25, each question in its project's library.

It writes `ingestion.json` and `ingestion.md` to `reports/evals/` (or `--out`) and prints the
summary. The whole corpus takes about a minute per configuration.

## The recorded run

The recorded run is in
[`packages/exactdocs/evals/results/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/results)
(`reports/` is not committed). `--check` compares a run with it, in every configuration both
measured:

- coverage may not drop;
- the integrity and heading counts may not rise: `articles_without_chunks`, `cuts_in_*`,
  `lost_chars`, `empty_heading_paths`, `wrong_heading_paths`, `headings_missed`,
  `headings_extra`;
- BM25 recall@5 may not drop more than 2 points.

A run on another golden set (another fingerprint) or other projects fails until the run is
recorded again. When a change to the importer improves the numbers, record the run in the same
pull request.

!!! warning "Run it before the pull request"
    Neither pull requests nor releases run it. The manual *Eval* workflow (`eval.yml`) runs
    `--check` (step *Ingestion benchmark*); start it before a release that touches chunking. If
    you change the parser, the chunker or the import path, run
    `just ingestion-bench --offline --check` before you open the pull request.

Pull request CI only runs the benchmark's quick tests (`tests/evals/test_ingestion.py`,
`ingestion_bench.feature`) on a tiny local corpus.

## Configurations

| Name | Settings | What it does |
|---|---|---|
| `default` | split level 3<br/>`max_chars` 4,000 | today's default (#381): `#` to `###` start a chunk; a longer one is cut again at deeper headings |
| `h6` | split level 6<br/>no merging, no bound | every heading starts a chunk (the default before #381) |
| `h2` | split level 2<br/>no bound | only `#` and `##` start a chunk; deeper sections stay inside their parent |
| `merge-400` | split level 6<br/>`min_chars` 400<br/>`max_chars` 4,000 | every heading starts a chunk, then a chunk under 400 characters is merged with the next while the result stays within 4,000 |

- They are `CONFIGURATIONS` in `retrieval_eval/ingestion_cli.py`.
- `default` is whatever a new library gets, so it follows the shipped default; the others name
  every setting.
- When the default changed in #381, `h3-max-4000` became `default` and the old `default` became
  `h6`. The ingestion run was measured again (the same numbers under the new names) and the
  retrieval run relabelled.
- The section ceiling of #141 (splitting a long section at block boundaries) is not one of them
  yet: it is not exposed in the library settings.

## Metrics

Each metric is reported per project and version, and in total per configuration.

!!! note "The benchmark's own line reader"
    The checks of block structure use the benchmark's own line reader, not the importer's parser.
    Where the parser reads a fence, a heading or an indented block differently (MDX, MkDocs), the
    two disagree and the disagreement is counted.

    The reader knows fenced code (backticks or tildes, closed by the same marker at least as
    long), ATX and setext headings, pipe-table rows and list items. It does not know HTML blocks,
    MDX or indented code, on purpose.

### Coverage and integrity

| Metric | Definition |
|---|---|
| `coverage` | share of the golden set's distinct expected sections that start at least one chunk: a chunk's heading path is the section's[^missing] |
| `cuts_in_code_fence` | chunks that end inside a fenced code block (the line reader, fed the article's chunks in order, is inside a fence after the chunk) |
| `cuts_in_table`, `cuts_in_list` | chunks whose last line and the next chunk's first line are both table rows, or both belong to a list |
| `lost_chars` of `source_chars` | non-whitespace characters of the source that are in no chunk[^lost] |
| `articles_without_chunks` | selected files the importer stored no chunk for |

[^missing]: `missing_sections` lists every other one, marked `(held)` when it is still a heading
    inside a bigger chunk. `held_sections` counts those that start a chunk or are held.

[^lost]: The source is the file at the pinned commit, a symlink followed one hop as a reader of
    the repository sees it, front matter left out. Each chunk is looked for verbatim after the
    previous one's match.

### Chunk sizes

| Metric | Definition |
|---|---|
| `tokens_p50`, `tokens_p95`, `tokens_max` | chunk size in estimated tokens, `ceil(characters / 4)` (retrieval's `CHARS_PER_TOKEN`); nearest-rank percentiles |
| `small_chunks`, `small_share` | chunks under 50 tokens (`MIN_USEFUL_TOKENS`, about a heading and a sentence or two) |
| `multi_top_chunks`, `multi_top_share` | chunks holding more than one top-level heading (a heading whose path has one element: the H1, or the H2s of a page without H1) |

### Headings and markup

| Metric | Definition |
|---|---|
| `empty_heading_paths` | chunks with an empty heading path: text before the first heading, or an article with no heading |
| `wrong_heading_paths` | chunks whose heading path holds an empty heading or markup that should have become plain text[^markup]; examples in `wrong_heading_examples` |
| `headings_missed`, `headings_extra` | per article, how many fewer (more) headings the chunks record than the line reader finds outside fenced code, summed |
| `articles_without_h1` | readable, non-empty files with no level-1 heading |
| `unexpanded_includes` | chunks holding an include the docs build expands and Markdown does not (`{!file!}`, `--8<--`) |
| `mkdocs_blocks_as_code` | MkDocs admonitions and content tabs (`!!!`, `???`, `===`) whose 4-space-indented body Markdown reads as an indented code block |

[^markup]: `{#id}`, `[#id]`, `[text][ref]`, `[text](url)`, `{/*`, `{!`. An HTML tag does not
    count: a heading's code span may hold one.

`examples` keeps up to ten article keys (`<project> <version>:<path>`) per article-level metric.
Next to them, per configuration, `bm25` holds recall@1/5/10, MRR, the wrong-version rate and the
misses of the golden set's answerable cases, with the suite's own evaluators.

## Matching a hit across chunking depths

A configuration that cuts coarser or finer than the golden set's sections would otherwise lose
every hit to a heading path that no longer exists. So a returned chunk of the expected version and
article answers the expected section when:

- its heading path is the expected one (the section, or a part of it split at its blocks);
- or the expected path is a non-empty prefix of it (a finer cut: the chunk is part of the section
  with its subsections);
- or the chunk holds the expected heading.

The last is read from what the chunk holds, not guessed from heading paths:

- the chunker records every heading it puts in a chunk (`headings` of the stored chunk);
- the benchmark reads those records by chunk ID once the corpus is imported;
- each returned hit carries its chunk ID.

So these all count (#503):

- a coarser cut that keeps the section inside its parent;
- a cut at `max_chars` that keeps it in a sibling's chunk;
- sections merged by `min_chars`.

Until #503 only a chunk named after a parent of the section counted, and `h2` and `merge-400` lost
6 to 7 points of recall@5 to it. `recall_at_5_exact` is recall@5 with only the exact heading path,
for comparison. The rule is `golden_run.held_match`.

## The JSON report

`ingestion.json` is the source the published results (#349) are built from. Its layout is stable,
and `schema_version` changes when a field is renamed or removed.

??? info "Fields of `ingestion.json`"
    - `schema_version`, `golden` (the golden set's fingerprint), `cases`, `projects`,
      `min_useful_tokens`, `chars_per_token`;
    - `configurations`: one entry per configuration with
        - `name`, `about`;
        - `chunking`: the library settings (`split_level`, `min_chars`, `max_chars`, `chunker`);
        - `totals`: the metrics above over the whole corpus;
        - `bm25`: `answerable`, `recall_at_1`, `recall_at_5`, `recall_at_10`, `mrr`,
          `recall_at_5_exact`, `wrong_version_rate`, `misses`, `errors`;
        - `versions`: per `project` and `version`, `library`, `commit` and the same `metrics`.

## Running more retrieval modes on the golden set

`retrieval_eval/golden_run.py` is the golden set's multi-library runner:

- `golden_retriever` sends each question to its project's library through the suite's
  `SearchDocsRetriever`;
- `run_golden` scores the whole set with the suite's evaluators and `evaluate_mode`, with the
  exact or the held match rule.

The ingestion benchmark runs BM25 through it, and the
[retrieval benchmark](retrieval-benchmark.md) every mode.
