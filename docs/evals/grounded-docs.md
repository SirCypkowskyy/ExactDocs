# Grounded Docs

!!! abstract "TL;DR"
    - [Grounded Docs](https://github.com/arabold/docs-mcp-server) is the closest open-source
      alternative to ExactDocs. It runs locally, so the run (#492) compares both tools on the same
      documentation at the same commits, the same questions and the same embedding model.
    - The pinned release is `@arabold/docs-mcp-server@3.4.1`, in two configurations: `full-text`
      and `bge-small-en-v1.5` (full-text and vector search).
    - Answers are scored with the [text scorer](text-scoring.md), next to ExactDocs' BM25 at
      `default` in the same run, with paired tests.
    - A full run takes about half an hour on 4 CPUs. It runs by hand, never in pull request CI.
      Results are on [Comparison with other tools](../benchmark/comparison.md).

`@arabold/docs-mcp-server` (MIT) is a self-hosted MCP server that:

- indexes each library version separately, from websites, GitHub, npm, PyPI or local folders;
- searches it with full-text search, and with vector search too when an embedding model is
  configured.

| Part | Code |
|---|---|
| the run | `retrieval_eval/grounded_docs_cli.py` |
| its report, comparison and Markdown | `retrieval_eval/grounded_docs.py` |
| the local embedding endpoint | `retrieval_eval/openai_embeddings.py` |

```bash
exactdocs models pull BAAI/bge-small-en-v1.5      # the vector configuration's model, once
just grounded-bench                               # both configurations, every project: about half an hour on 4 CPUs
just grounded-bench --configs full-text           # full-text search only: a few minutes
just grounded-bench --resume                      # after an interruption: keeps the versions already indexed
just grounded-bench --out packages/exactdocs/evals/results   # refresh the recorded run, then `just bench-pages`
```

## What it needs

- Node.js 22 and npm.
- The golden corpus cache (`--offline` uses it as it is).
- For the vector configuration, the model in `EXACTDOCS_MODELS_DIR` (or `--models-dir`).

The first run installs the pinned release, `@arabold/docs-mcp-server@3.4.1` (`VERSION`):

- with `npm install` into `~/.cache/exactdocs/grounded-docs/3.4.1/` (`--home` moves the whole
  directory);
- it refuses an install whose `package-lock.json` does not carry the registry's integrity hash
  (`INTEGRITY`).

Changing the release means recording its responses for the tests again
([When it runs](#when-it-runs)) and a new run.

## What a run does

### The same files

- For every pinned version, the files the ExactDocs importer takes at the pinned commit are
  written byte for byte under their repository paths to `<home>/corpus/<project>/<version>/`.
  These are the project's include and exclude paths, `.md` and `.mdx`, a symbolic link followed
  one hop: the same selection as [the ingestion benchmark](ingestion.md).
- Grounded Docs' `scrape` command indexes that folder (`file://`) as library `<project>` at
  version `<version>`, into the configuration's own data directory,
  `<home>/stores/<configuration>/`.
- The report lists, per version, the articles offered, the pages and chunks stored, and every
  offered article it did not store.

### Its documented defaults

The run writes Grounded Docs' configuration file (`--config`, which it reads and never writes)
with three settings:

| Setting | Value | Why |
|---|---|---|
| telemetry | off | |
| the one root `file://` may read | the corpus folder | its default is `~/Documents`, which a headless machine lacks |
| `embeddings.requestTimeoutMs` | 300,000 instead of 30,000 (`REQUEST_TIMEOUT_MS`) | see below |

The local endpoint embeds one request at a time on the CPU, and Grounded Docs sends several at
once. So a request can wait more than 30 seconds for its answer, after which the client gives up
and sends it again. That timeout decides how long it waits, nothing it indexes or ranks.

Everything else keeps its default:

- scraping, and its default exclusion patterns (`CHANGELOG.md`, `**/legacy/**`, ...);
- splitting (500, 1,500 and 5,000 characters);
- search (reciprocal rank fusion of full-text and vector results);
- result assembly.

The crawl's depth (3) and page (1,000) limits are raised only for a version whose folder is deeper
or larger, so that every article is offered (`limits`; the report records what was passed).

- A command inherits no provider credential or `DOCS_MCP_*` variable from the shell.
- It runs with `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` (local files need no browser).
- The configuration in effect (`docs-mcp-server config`) is recorded per configuration.

### Two configurations

| Configuration (`CONFIGURATIONS`) | Search |
|---|---|
| `full-text` | no embedding model: what Grounded Docs does when no provider credentials are set |
| `bge-small-en-v1.5` | full-text and vector search with ExactDocs' best local model, `BAAI/bge-small-en-v1.5` |

How the vector configuration reaches the model:

- Grounded Docs reaches a local model through an OpenAI-compatible server (`OPENAI_API_BASE`).
- The run serves the model `exactdocs models pull` fetched (the same quantized ONNX file at the
  same pinned revision, loaded by fastembed as ExactDocs loads it) at `POST /v1/embeddings` on a
  loopback port.
- It sets a dummy `OPENAI_API_KEY` (the endpoint checks none) and
  `DOCS_MCP_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`.
- Documents and queries are embedded alike, with no query instruction, as ExactDocs embeds them
  with this model.
- Grounded Docs' table of known models gives this one 512 dimensions, so it pads each
  384-dimension vector with zeros, which changes no distance between two vectors.
- The model truncates a text to 512 tokens, in both tools.

### The questions

- They go through Grounded Docs' MCP server (`docs-mcp-server mcp --protocol http` on a loopback
  port).
- One `search_docs` call per case, with the case's project as the library, its version and its
  question, and a limit of 10 (`TOP_K`, the cut-off ExactDocs is measured at).
- The tool always searches with `exactMatch: false`. The version asked is indexed, so that is the
  one searched.
- Its response is one text, each result after a rule of 60 dashes and `Result <n>: <url>`.
  `split_results` cuts it into the results, in order.

### Scoring

- Scoring is the text scorer's (`text_row`), so every metric of
  [Metrics of text results](text-scoring.md#metrics-of-text-results) is reported, with its
  interval.
- ExactDocs' BM25 at `default` answers the same questions in the same run and is scored the same
  way (the corpus imported model-free, each hit's chunk content as its text, as the calibration
  does).
- Every configuration is tested against it, case by case: McNemar mid-p for recall@1, @5 and @10,
  the sign-flip permutation test for MRR and nDCG@10.
- The report also lists ExactDocs' `bm25` and `hybrid:bge-small-en-v1.5` at `default` from the
  recorded retrieval benchmark run, with paired tests against their rows, when that run measured
  the same golden set on the same projects. That run (`results/retrieval.json`) is scored by chunk
  ID, which agrees with the text scorer on 99.8% of decisions at `default`.

### Indexing time and size

- **Indexing time** is the wall time of each `scrape` command (the Node.js start included, about
  two seconds).
- **Index size** is the data directory (its SQLite database) once every version is indexed.
- For the vector configuration the report also counts what the endpoint embedded per version and
  for the questions, and how many requests a client abandoned.

## Reading the numbers

!!! warning "Keep these in mind"
    - **Grounded Docs returns bigger results.** Each is the matching chunks with the context it
      assembles around them: parent sections, a preceding and two following siblings, child
      sections. A bigger result holds more sections, and the text scorer counts a hit when a
      result holds a section's text, so compare recall with the context tokens per question and
      the tokens to the first hit.
    - **Most results are version-neutral.** Most text of a pinned version is the same in the
      others, so the text scorer's wrong-version rate is a lower bound (see
      [Metrics of text results](text-scoring.md#version-neutral-results)). Grounded Docs searches
      only the version it is given, so a result of another version is not expected from it.
    - **No reranker and no "no answer" threshold.** Its full-text search can return nothing ("No
      results found") when no word of the question is indexed, which the run scores as an empty
      answer.
    - **The latencies are not comparable.** Grounded Docs' include a call through MCP over HTTP
      (and the query's embedding); the baseline's are ExactDocs' search alone, in-process.

## The Grounded Docs report

`grounded-docs.json` (`schema_version` 1, in `reports/evals/` or `--out`). `grounded-docs.md` is
the summary, and `just bench-pages` fills [Comparison with other tools](../benchmark/comparison.md)
from the recorded run. Since #575 the summary also compares every result within 1,000, 2,000 and
4,000 tokens of the text it returned, read whole and cut at the budget
([Within a token budget](retrieval-benchmark.md#within-a-token-budget)), with the paired tests of
each Grounded Docs configuration against ExactDocs on both.

??? info "Fields of `grounded-docs.json`"
    - `golden`, `cases`, `projects`, `corpus` (every pinned version's commit), `date` (when the
      run ended);
    - `tool`: `name`, `package`, `version`, `integrity`, `node`, `search`, `top_k`;
    - `environment`: the ExactDocs commit the run started from, Python, platform, CPUs;
    - `scorer`: the text scorer's settings;
    - `statistics`: seed, resamples, confidence, significance level;
    - `baseline`: ExactDocs' BM25 at `default` (`result`, `context_tokens_interval`, `rows`);
    - `recorded`: ExactDocs configurations from `retrieval.json` (`configuration`, `chunking`,
      `metrics`, `environment`);
    - per configuration, in `runs`:
        - `configuration`, `about`;
        - `settings`: Grounded Docs' configuration in effect, its paths shown as `<store>` and
          `<corpus>`;
        - `variables`: the environment variables set;
        - `embedding`: `model`, `revision`, `dimensions`, `stored_dimensions`, `served_by`, and
          `indexing` and `questions`, each `requests`, `texts`, `tokens`, `seconds`, `abandoned`;
        - `indexing`: per version, `seconds`, `offered`, `indexed`, `chunks`, `embedded`,
          `max_depth`, `max_pages`, `not_indexed`, `embedding`;
        - `index_seconds`, `index_bytes`;
        - `result`: the text scorer's metrics overall, by kind and by project;
        - `context_tokens_interval`;
        - `rows`: every case's row, for intervals and paired tests;
        - `versus`: per ExactDocs result, `against`, `scored_by`, `tests`;
        - `errors`: questions whose search failed, scored as empty;
        - `cases_not_indexed`: answerable cases none of whose listed articles was indexed.

The command exits with 1 (`problems`) when:

- a question failed;
- a version got nothing indexed;
- a chunk of the vector configuration got no vector.

## When it runs

By hand, or with the manual workflow `.github/workflows/grounded-bench.yml` on the self-hosted
runner (input `args`, e.g. `--configs full-text`; the report is the `grounded-bench` artifact).
Never in pull request CI.

Pull request CI runs the quick tests (`tests/evals/test_grounded_docs.py`,
`test_openai_embeddings.py`, `grounded_docs.feature`):

- they replay Grounded Docs 3.4.1's real `search_docs` responses
  (`tests/fixtures/grounded_docs_responses.json`) through a stand-in
  (`tests/fixtures/grounded_docs_stand_in.py`);
- the responses were recorded on the retrieval benchmark's tiny corpus in both configurations and
  on three synthetic pages, with the corpus path replaced by `file:///corpus`.

The data directories stay in `<home>/stores/` after a run, for the agent benchmark's Grounded Docs
arm (#495) to search ([Setting up the arms](agent-bench.md#setting-up-the-arms)). `--resume` reuses them and asks the questions again. That is how a scorer
change is applied without indexing again: about three minutes on 4 CPUs for both configurations,
the ExactDocs baseline included.
