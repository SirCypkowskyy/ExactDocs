# The retrieval grid

!!! abstract "TL;DR"
    - The retrieval benchmark tries heading chunking only. The grid (#494) cross-tests what it
      never tried: token windows with overlap, title and heading-path prefixes, widening to the
      parent section, larger embedding models.
    - Two plain baselines put every number in context: a keyword grep over the raw files and a
      fixed-window RAG.
    - None of it changes what ExactDocs ships. A variant that wins significantly gets a follow-up
      issue to ship it.
    - It runs by hand and resumes where it stopped. A full grid is meant for the self-hosted runner.

The grid tries:

- fixed token windows with overlap;
- the article title and heading path put in front of the text that is embedded or indexed;
- small heading chunks widened to their parent section when read;
- larger embedding models;
- two plain baselines to read every number against: a keyword grep over the raw files and a
  fixed-window RAG.

```bash
just retrieval-grid --offline                      # every cell of evals/golden/matrix.yaml
just retrieval-grid --offline --cells 'grep,window-*'
EXACTDOCS_MODELS_DIR=~/.cache/exactdocs/models just retrieval-grid --offline
```

## The grid file

`packages/exactdocs/evals/golden/matrix.yaml` declares the cells and, under `defaults`, the cell
each budget is tested against: what ExactDocs ships for it (BM25 at `default` for both `none` and
`local`, [Recommended defaults](../benchmark/defaults.md)).

A cell is one of two kinds:

| Kind | Declared as | Imported and searched by | Scored by |
|---|---|---|---|
| app cell | `app: <configuration>`, optional `chunking` | ExactDocs itself, exactly as `just retrieval-bench` runs it | chunk ID |
| eval-only cell | `name` and `search` | the grid, in process, over the pinned versions | the [text scorer](text-scoring.md) |

### App cells

An app cell is a configuration of the retrieval benchmark (`bm25`, `hybrid:bge-base-en-v1.5`,
`bm25+ce`, `hybrid:hosted`, ...). Hosted ones run only with `--allow-providers`.

### Eval-only cells

The grid cuts, indexes and searches the pinned versions itself, in process, and scores the text it
returns. Settings:

| Setting | Values |
|---|---|
| `chunking` | a heading chunking of the ingestion benchmark (`default`, `h6`, `h2`, `merge-400`), cut with ExactDocs' own chunker |
| `window`, `overlap` | windows of whole lines of about `window` estimated tokens, the next starting so that at most `overlap` tokens are shared |
| `search` | `bm25`, `dense`, `hybrid` or `grep` (below) |
| `prefix_indexed` / `prefix_embedded` | put `title > heading > path` in front of the text indexed for BM25, or of the text embedded |
| `expand: parent` | return each hit's parent section with its subsections instead of the hit |
| `expand: article`, `neighbours` | group the top 10 hits by article, as Grounded Docs does (#575) |
| `embedding` | a local model pulled with `exactdocs models pull` |
| `against` | the cell this one is a variant of, its control (#575) |

- **Windows** ignore headings, code blocks and tables. A window's heading path is the one it
  starts in.
- **`search`**:
    - `bm25`: an in-memory SQLite FTS5 table with the columns, weights and tokenizer of ExactDocs'
      index, BM25 statistics over the whole corpus, each search filtered to the version asked;
    - `dense`: cosine to the query over the `embedding` model's vectors;
    - `hybrid`: both, fused by RRF as ExactDocs fuses them;
    - `grep`: the baseline below.
- **Prefixes**: the text returned is never prefixed. ExactDocs' own index already weights the
  heading path in its own columns; the prefix adds the title and puts the path in the text.
  ExactDocs' own vector index already embeds the title and the heading path in front of each chunk
  (embedding input format 1), so `prefix_embedded` is the eval-only form of what it ships.
- **`expand: parent`**: a top-level section widens to itself, and a widened text returned twice is
  returned once.
- **`expand: article`**: each article is one result, ranked by its best hit, holding its hits and
  the `neighbours` chunks on either side of each (1 when not given, `ARTICLE_NEIGHBOURS`; 0 for the
  hits alone), in article order, each chunk once. Heading chunkings only.
- **`embedding`**: a cell whose model is not pulled is reported unavailable, with the command.
- **`against`**: the report also tests the variant against its control, case by case, on recall@k,
  MRR, nDCG@10 and recall within each token budget
  ([Within a token budget](retrieval-benchmark.md#within-a-token-budget)). It changes nothing the
  cell returns, and running a variant with `--cells` runs its control too.
- **Embeddings are kept.** The grid embeds each distinct text once (a chunk that is the same in
  several pinned versions is one text) and keeps every slice of 256 embedded texts in
  `<out>/embeddings/`, under a hash of the model and the texts. A cell whose texts were embedded
  before reads them back, and a cell interrupted while embedding takes up where it stopped. A
  cell's index cost still counts the seconds embedding its texts took the first time.

### The control

`default/bm25`, the grid's own BM25 at ExactDocs' chunking, is the control. It should score as the
app's `bm25@default` does, so a gap between an eval-only variant and the default comes from the
variant, not from the grid's search.

## The baselines

| Baseline | What it does |
|---|---|
| `grep` | `rg -i -w -C 3` over the raw Markdown files of the version asked, with the question's content terms (`question_terms`, stop words left out) |
| `rag:window-256+64/bge-small` | fixed windows embedded with the same model as hybrid search, dense search only |

For `grep`, overlapping matches merge, and snippets rank by the distinct terms they hold, then by
their matching lines. It needs no index.

## Reading the report

The report is `<out>/retrieval-grid.json` and `.md` (default `reports/evals/grid/`).

- `bench` is the retrieval benchmark's report: every cell with its metrics, 95% intervals,
  breakdowns and index cost, and the paired test of every cell against its budget's declared
  default (#489).
    - `index` holds seconds and embedding tokens; eval-only cells count cutting and indexing too.
- `recommendations` holds those declared defaults, not a pick.
- `text`: per text-scored cell, the text scorer's numbers (context tokens per question, tokens to
  the first hit, facts found). Widening to the parent or a larger window returns more text.
- `ingestion`: per eval-only chunker, the ingestion benchmark's metrics (#346), so the report says
  where windows cut code blocks, tables and lists.
    - Coverage and lost characters say little of windows (they start mid-section and overlap), so
      the summary shows the sections held instead.
- `versus_control`: per variant that names a control (`against`), the paired tests against it,
  shown under *Against each variant's control*.
- Every cell also reports recall within 1,000, 2,000 and 4,000 tokens, under *Within a token
  budget*: whole results for every cell, and cut at the budget for the cells scored from text.
- `just bench-pages` shows the recorded run of the rank-1 cells
  (`results/retrieval-grid-rank1.json`, #575) on [Retrieval results](../benchmark/retrieval.md).

!!! note "Wrong versions in text-scored cells"
    A text-scored cell searches only the version asked. A result the text scorer places only in
    another version is a text that crosses sections: it counts in the wrong-version rate and does
    not fail the run. A wrong version of an app cell fails it, as in the benchmark.

## Resuming

- Each finished cell is written to `<out>/cells/<name>.json` with a key of its settings, the
  golden set and the pinned commits.
- A later run reuses a cell whose key matches (`resumed` in the report) and runs the others. So an
  interrupted run goes on where it stopped, and a changed cell runs again.
- `--fresh` runs every cell; `--cells` runs some (the declared defaults always run).

## When it runs

By hand.

- The tests run the grid on the tiny corpus with the term-hash stand-in embedding
  (`tests/evals/test_retrieval_grid.py`, `retrieval_grid.feature`). No model is downloaded, and
  their numbers are never results.
- A full grid embeds the corpus once per embedding cell: about 50 minutes per chunking for
  `bge-base` on a 4-CPU runner (see [the recorded run](retrieval-runs.md#the-recorded-run)). So it
  is meant for the self-hosted runner.
