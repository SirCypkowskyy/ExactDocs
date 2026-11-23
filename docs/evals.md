# Retrieval evals

Retrieval modes are compared with numbers before one becomes a default. The eval suite runs one
dataset of questions through every retrieval mode this build can run, on the fixture docs
repository imported for real, and reports per mode how often the right section comes back, how
often anything of another version does, what it cost and how long it took. The decisions behind
it are in [AI retrieval decisions](decisions/ai-retrieval.md#evaluation). The fixture is imported
with every heading starting a chunk (`split_level` 6, no bound), because the dataset names its
`####` sections; a new library's default since #381 would hold them inside their parent.

The results of the benchmarks below (the golden set, ingestion, retrieval and agent) and the
defaults they recommend are published in the [Benchmark](benchmark/index.md) section; this page
is the reference for running them.

The suite is development and release tooling: it lives in
[`packages/exactdocs/evals/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals),
outside the package, and [Pydantic Evals](https://ai.pydantic.dev/evals/) (`pydantic-evals`
2.60.0) is in the `dev` dependency group, not in an extra. Nothing of it ships in the wheel or
the image.

## When it runs

**On releases and locally, not on pull requests.** CI on a pull request or a push to `develop`
or `main` runs no eval step, and `uv run pytest` skips the suite's end-to-end tests. The release
workflow (`.github/workflows/release.yml`, job *Retrieval eval*) runs all of it before anything
is published, and a failing gate stops the release (see [Tiers](#tiers)). So a ranking
regression is caught when a release is cut, not on the pull request that caused it: **if you
change ranking, chunking, the search index, a retrieval mode, the dataset or the fixture, run
`just eval` (and `uv run pytest -m eval`) before you open the pull request**, and say in it that
you did.

The suite's pytest tests that import the fixture and run the suite end to end carry the marker
`eval`, which `addopts` deselects (`-m "not eval"` in `pyproject.toml`). The quick ones (the
dataset, fingerprints, evaluators and gates on stand-in retrievers) stay in the default run.
`uv run pytest -m eval` (or `just test -m eval`) runs the marked ones; a new test that imports
the fixture and searches it gets `@pytest.mark.eval`. The behave scenarios in
`retrieval_eval.feature` take a few seconds and stay in the default run.

## Running it

```bash
just eval                       # every mode; those that cannot run are listed with the reason
just eval --modes bm25          # one mode
just eval --report out.json     # JSON report elsewhere (default: reports/evals/retrieval.json)
just eval --baseline develop.json --ratchet --reference-dataset develop.yaml   # a branch against develop's baseline
just eval --configured-models --local-roles embedding,reranker   # local models from EXACTDOCS_AI__...
                                # (after `exactdocs models pull`; see the release's eval job)
just eval --offline-embedding --ratchet   # hybrid on an in-process term-hash embedding (no model): what the release runs
just eval --help
```

It builds the fixture repository in a temporary directory, imports `v1.3.0`, `v1.4.0` and `next`
with the real importer, then asks `search_docs` for the top 10 of every question in each mode, and
reads every returned chunk back with `read_chunk`. It prints a Markdown summary, appends it to
`$GITHUB_STEP_SUMMARY` when that is set, writes the JSON report, and exits with 1 when a gate
fails (2 for a usage error, such as a `--baseline` or `--reference-dataset` path that does not
exist). A case whose version or expected section the fixture does not have fails the suite too,
rather than counting as a miss.

By default the run is **model-free**: the app is built with no model role, whatever
`EXACTDOCS_AI__...` configures, so only BM25 runs. `--configured-models` uses the configured
models instead. Before the questions, every version is embedded the way the `embed` jobs would,
when the embedding role may be called (`--local-roles embedding` or `--allow-providers`).

`--offline-embedding` runs `hybrid` without any model: the embedding role is an in-process
stand-in that hashes each term of a text into one dimension (`HashEmbeddingModels(by_terms=True)`,
see `tests/fixtures/offline_embedding.py`). Texts sharing terms are near, so the run checks the
fusion and the wrong-version gate of hybrid, end to end; it finds no paraphrase a real model would,
so its recall says nothing about whether hybrid should be a default: the report gives hybrid's
`eligible_as_default` as `null` with `not_judged: "offline embedding"`, the summary says so, and
the flag refuses `--write-baseline` and `--configured-models`. Tokens and USD per question are what
the spend ledger grew by during each search, so hybrid's include its query's embedding.
`uv run pytest -m eval` runs the same BM25 run (`tests/evals/`), so a ranking change that breaks a
gate also fails those tests.

## The dataset

`packages/exactdocs/evals/retrieval_eval/dataset.yaml`, in Pydantic Evals' YAML format. Each case
is a question pinned to one version, and the section that answers it:

```yaml
- name: 'v1.4.0: Which failures does the client repeat by default?'
  inputs: {query: Which failures does the client repeat by default?, version: v1.4.0}
  metadata: {kind: question}
  expected_output:
    hits:
    - version: v1.4.0
      article: docs/guide/resilience.md
      heading_path: [Resilience, Retry policy, retry_policy]
```

- `kind: identifier` cases are the fixture's
  [`expected-queries.yaml`](https://github.com/SirCypkowskyy/ExactDocs/blob/develop/packages/exactdocs/tests/fixtures/docs-repo/expected-queries.yaml),
  one case per asserted version, tag filters included. A test keeps the two in step: a query added
  to the ranking table must be added here too.
- `kind: question` cases are natural-language questions, the way an agent asks, often in words
  the section does not use ("replace an API key without downtime" for *Rotating tokens*).
- `hits: []` means the version has no answer (`retry_policy` in `v1.3.0`). Such a case counts for
  the wrong-version rate only: whatever a mode returns for it must still be of that version.

To add a case, add it to the YAML; a test checks that its section exists in that version. If the
content it needs is missing, extend the fixture as its README says. Then rewrite the baseline
([Changing the dataset](#changing-the-dataset)).

## Metrics

| Metric | Over | Meaning |
|---|---|---|
| recall@1, recall@5, recall@10 | questions whose version has an answer | the expected section is in the first k results |
| MRR | the same | mean of 1 / its rank (0 when it is not in the top 10) |
| wrong-version rate | every question | share of questions with at least one result of another version |
| p50 / p95 latency | every question | time of the search alone (not the reads below), one question at a time |
| tokens / USD per question | every question | what the models cost, read from the spend ledger around each search; 0 for BM25 |

The version of a result is the version **of its chunk**, not the version the answer names: every
returned chunk ID is read back with `read_chunk`, which serves it from the version the ID was issued
for (chunk IDs hash their version), and its version and commit are compared with the question's. So
a search that lets another version's chunk through fails the suite even when it labels that chunk
with the version asked for. (Today `search_docs` already drops a pipeline's hit of another
version, since it loads chunks from the asked version's manifest only; the eval is the check that
this stays true for every mode and adapter.)

**Agentic runs are also checked from their traces** (#99), and only here. The suite hands the app
a recorder of the agentic explorer's reads (`Container.build(agent_reads=...)`; every
`run_on_fixture` builder takes it), so each answer carries its run's trace: for every read the
agent made, the version and manifest it was bound to and those of what it returned to the agent
(never its arguments or the text). `StayedInVersion` asserts `stayed_in_version` for each case: a
read bound to another version, one that served something of another version or manifest, reads
bound to more than one manifest, or an `agentic` answer with results but no trace fail it. This
checks what the agent was shown on the way, where the wrong-version rate checks what it
returned. The report counts `traced_runs` and lists the failing cases in `left_version_cases`;
any fails the suite, and a mode with one is never `eligible_as_default`.

The JSON report also lists, per mode, the cases with a wrong version (and the offending results),
the questions whose section was not in the top 10, the questions that raised, how many a
cheaper mode answered (`fallbacks`), how many a reranker reordered (`reranked`) and, with a reranker
role configured, how many came back with results but not reranked (`rerank_fallbacks`: the
reranker failed or timed out, whatever `fallback_reason` shows); the Markdown
summary repeats the last two for a mode that was reranked.

### Evaluating the reranker

Reranking is a flag on top of every mode, so a run with a `reranker` role configured measures each
mode reranked. Compare two runs on the same dataset: one without the role and one with it, e.g.
`EXACTDOCS_AI__RERANKER__MODEL=cohere:rerank-v3.5 just eval --configured-models --modes bm25
--allow-providers` (a hosted reranker) or `--local-roles reranker` (one running on this machine,
such as TEI on localhost). Without either flag the reranked modes are `skipped`, and no request
leaves the machine. Check `rerank_fallbacks` is 0: a reranker that timed out was not measured.

### Evaluating the LLM judge

The judge (#96) reranks like the cross-encoder, so it is measured the same way: a run with
`EXACTDOCS_AI__RERANK_WITH=judge` and a `judge` (or `llm`) role measures each mode reranked by
it, e.g. `EXACTDOCS_AI__JUDGE__MODEL=corp:gpt-4.1-mini EXACTDOCS_AI__RERANK_WITH=judge just eval
--configured-models --modes bm25 --allow-providers`. Each mode's outcome says what reranked it
(`reranker`: `cross_encoder` or `judge`), and the judge's tokens and USD reach
`tokens_per_question` / `usd_per_question`. Compare with a run reranked by the cross-encoder (or
none) on the same dataset; check `rerank_fallbacks` is 0, as a refused or timed-out judgment
keeps the mode's order and was not measured. A hosted judge is `skipped` without
`--allow-providers` (or `--local-roles judge` for one on this machine, such as Ollama). The release runs
it only on a stand-in (`tests/evals/`, `offline_judge_container`, marked `eval`): a pydantic-ai
`FunctionModel` that rates candidates by the query words they share, priced, so the plumbing, the
wrong-version rate of 0 and the cost per question are checked at every release (and by
`uv run pytest -m eval`) without a provider; its recall says
nothing about a real judge. The manual *Retrieval eval (real providers)* workflow measures a
real one with `EVAL_JUDGE_MODEL` and `EVAL_RERANK_WITH=judge`.

## Gates

- **Wrong-version rate must be 0 for every mode that ran**, whatever its recall. One result of
  another version fails the suite.
- **recall@5 may not drop more than 2 points below the baseline**: at a release, the
  `baseline.json` committed in the tagged tree; when you check a branch, the one you pass with
  `--baseline` (such as `develop`'s). A drop fails the suite for BM25 and is a warning for the
  report-only modes. A gating mode with no baseline entry is a warning (its recall is then not
  gated).
- **The stored baseline only moves up** (`--ratchet`): checked against `develop`'s copy, the
  branch's `baseline.json` may not store a lower BM25 recall@5 than `develop`'s, and a value it
  raises must be what the run measures (a stored recall@5 above the measured one fails). The
  release passes `--ratchet` with no `--baseline`, so the committed file is compared with itself
  and the check that remains is that it was recorded for this dataset.
- A run compares with another baseline only **on the same dataset**; when the dataset changed,
  see [Changing the dataset](#changing-the-dataset).
- **No agentic run may read outside the version asked for**, from its trace (above).
- A question whose search raises fails the suite.
- **A mode becomes a default only when the suite shows it beats BM25's recall@5 by at least
  5 points with a wrong-version rate of 0.** The report marks such a mode `eligible_as_default`;
  changing the default order (`DEFAULT_MODE_ORDER`) without that is not accepted. It holds only
  `bm25` today: for `hybrid` only a real embedding model's run counts (#245), never the term-hash
  stand-in's, whose report says `not judged (offline embedding)`; the same holds for
  `hybrid_hyde`, which the release runs only on a stand-in LLM (below) and which needs a run
  with a real LLM and embedding model before it can become a default.

The baseline is `packages/exactdocs/evals/retrieval_eval/baseline.json`: recall@1/5/10, MRR and
the wrong-version rate of each mode that ran (no latency, which depends on the machine), and the
`dataset` fingerprint they were measured on. The release gates on the copy committed in the
tagged tree; no pull request job checks it, so a reviewer checks a change to it in the diff. To
hold a branch to `develop`'s bar, fetch `develop`'s `baseline.json` and `dataset.yaml` and run
`just eval --baseline develop.json --ratchet --reference-dataset develop.yaml`. A change that
improves ranking refreshes it in the same pull request, where the diff shows the new numbers:

```bash
just eval --write-baseline
```

## Changing the dataset

The fingerprint (`sha256:...` in `baseline.json`) is a hash of what the dataset states: each
case's question (`inputs`, defaults left out) and the version, article and heading path of each
section it expects. Renaming, reordering or commenting cases keeps it, and so does a new field with
a default in the dataset's models; adding, removing or changing a question or an expected section
changes it. Numbers measured on different datasets are not comparable (harder questions lower
recall without anything getting worse), so:

1. Change `dataset.yaml` (see [The dataset](#the-dataset)).
2. Run `just eval --write-baseline` and commit the new `baseline.json` in the same pull request.
   It records the new fingerprint and the recall measured on the new dataset, which may be lower.
3. Checked against `develop`'s baseline (`--baseline develop.json --ratchet
   --reference-dataset develop.yaml`, the run to do before the pull request), `develop`'s
   baseline has another fingerprint, so the baseline is **reset**:
    - the drop gate compares with the branch's `baseline.json`, and the ratchet against `develop`
      is off; once the pull request is merged it starts again from the new baseline;
    - the branch's stored recall@5 must be exactly what the run measures, neither above nor below,
      since it becomes the next bar;
    - **`develop`'s dataset is still run**, with the branch's code, and gated against `develop`'s
      baseline as usual (`--reference-dataset`; its summary is *Retrieval eval on the reference
      dataset*). A question of the old dataset whose version or section the fixture no longer has
      fails the run instead of being skipped. So rewording or adding a question cannot hide a
      ranking regression: the old questions still catch it;
    - the reset is reported as a warning annotation (*Eval baseline reset*) and in the summary
      (**Baseline reset: the dataset changed (...)**).

If `baseline.json` was not rewritten, its fingerprint is not the dataset's and a run with
`--ratchet` (the release's included) fails with "was recorded for dataset ..., not this one".

**The fixture is not part of the fingerprint.** A change to the fixture docs repository
(`packages/exactdocs/tests/fixtures/docs-repo`), such as a new distractor article, is gated like a
ranking change: recall@5 may not drop more than 2 points below the baseline, and there is
no reset path (a reset still runs `develop`'s dataset against `develop`'s baseline, on the new
fixture). A fixture change has to keep BM25's recall@5 within those 2 points.

## The golden set

The fixture is synthetic. The benchmarks of E13 (#344) run on the **golden set** (#345)
instead: questions with known answers about real projects' documentation, each pinned to a
version. It lives in
[`packages/exactdocs/evals/golden/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/golden):

- `corpus.yaml`: the corpus manifest. Per project: the repository, the docs paths it is imported
  with (`include`, `exclude`, as a library takes them), the licence and attribution, and one
  pinned commit per version.
- `cases/<project>.yaml`: that project's cases, one file per project so several people can add
  cases without conflicts. The format is the retrieval dataset's own (Pydantic Evals, the models
  in `retrieval_eval/dataset.py`); `retrieval_eval.golden.load_golden()` reads every file as one
  dataset.

Nothing of these projects is vendored here. The commands fetch each pinned commit with
`git fetch --depth 1` into a cache outside the repository: `$XDG_CACHE_HOME/exactdocs/golden`
(`~/.cache/exactdocs/golden`), one bare repository per project, about 65 MB in all. Change it
with `--cache-dir`.

```bash
just golden-validate                      # fetch what is missing, then check every case
just golden-validate --projects zod       # one project's sections (the rules are checked for all)
just golden-validate --offline            # no network: the cache must already hold the commits
just golden-import                        # fetch, then import every pinned version for real
just golden-import --data-dir ./golden-data --report out.json
```

`golden-import` imports each version with the real importer at exactly its pinned commit, from
the cache (the same import path as the fixture, `fixture_import.importer`), into a model-free
instance (a temporary data directory unless `--data-dir` names one). It records, per version, the
commit the catalog stored, the files imported, the import's problems and its time, in
`reports/evals/golden-import.json`, and fails when a recorded commit is not the pinned one. The
whole corpus imports in about 20 seconds.

### The corpus

| Project | Versions (pinned commit) | Docs paths | Licence, attribution | What it brings |
|---|---|---|---|---|
| [Starlette](https://github.com/encode/starlette) | 0.27.0 (`0c4b68a`), 0.52.1 (`e5b8a5d`), 1.10.0 (`8aa828c`) | `docs/` | BSD-3-Clause, © 2018 Encode OSS Ltd. | a small Markdown guide; 1.0 removed the startup and shutdown handlers |
| [Pydantic](https://github.com/pydantic/pydantic) | v1.10.22 (`5e6e87f`), v2.5.3 (`9f58e78`), v2.14.3 (`ea492e0`) | `docs/` | MIT, © 2017 to present Pydantic Services Inc. and individual contributors | a large MkDocs guide; v1 to v2 moved most pages; admonitions and content tabs; API pages that are mkdocstrings stubs |
| [TanStack Query](https://github.com/TanStack/query) | v4.36.1 (`6532ed3`), v5.0.0 (`3be9b45`), v5.90.3 (`4d8da1e`) | `docs/` | MIT, © 2021-present Tanner Linsley | guides and API reference, one tree per framework (near-duplicates); renamed options; every page moved between v5.0.0 and v5.90.3 |
| [Zod](https://github.com/colinhacks/zod) | v3.23.8 (`ca42965`), v4.0.17 (`cc63f95`), v4.6.7 (`b500a2e`) | `README.md`, `packages/docs/content/` | MIT, © 2025 Colin McDonnell | v3: one very long README; v4: an MDX site with JSX components and imports |
| [Electron](https://github.com/electron/electron) | v30.0.0 (`c37c7fd`), v38.0.0 (`7943386`), v45.3.2 (`9ee9e77`) | `docs/` | MIT, © Electron contributors, © 2013-2020 GitHub Inc. | a large hand-written API reference, tutorials, a breaking-changes page |

None of them ships a separate licence for its documentation: the repository's licence covers the
docs tree (no licence file or notice under the docs paths at the pinned commits). `corpus.yaml`
holds the full commit SHAs; each was resolved from the release tag with `git ls-remote --tags`
(the peeled commit of an annotated tag).

### A case

```yaml
- name: 'tanstack-query v5.0.0: What happened to the cacheTime option?'
  inputs:
    project: tanstack-query
    version: v5.0.0
    query: 'What happened to the cacheTime option?'
  metadata: {kind: version-change}
  expected_output:
    hits:
    - {version: v5.0.0, article: docs/react/guides/migrating-to-v5.md, heading_path: [Breaking Changes, Rename cacheTime to gcTime]}
    reference: v5 renames `cacheTime` to `gcTime` ("garbage collect" time); it only applies once a
      query is unused, after which its data is garbage collected.
    facts:
    - cacheTime is renamed to gcTime
    - it only takes effect once a query is no longer used
    - after that time the unused data is garbage collected
```

- `inputs`: the question (`query`), the `project` (the file it is in) and the `version` (a
  version name in `corpus.yaml`).
- `metadata.kind`: exactly one of `identifier-lookup` (an API name, option or command),
  `how-to` (steps to do something), `conceptual` (what something is or why it behaves so),
  `version-change` (what changed in or by this version), `cross-page` (needs sections of at least
  two articles), `unanswerable` (this version's docs do not answer it).
- `expected_output.hits`: the sections that answer it, best first, each the article path and the
  heading path from the top heading, as ExactDocs cuts the article (below). An `unanswerable`
  case has none.
- `expected_output.reference`: a short reference answer, as the pinned docs give it; for an
  unanswerable case, a sentence saying the version does not cover it.
- `expected_output.facts`: the short facts a correct answer must contain, each checkable on its
  own; none for an unanswerable case.

Every field the golden set adds has a default, so the fixture dataset and its fingerprint are
unchanged.

### What `golden-validate` checks

Every case file must load as the dataset's models, and every case must:

- have a unique `name`, a golden `kind`, the `project` its file is named after, and a `version`
  the manifest pins;
- have a reference answer; name sections and facts unless it is `unanswerable`, and neither when
  it is; name sections of the case's own version only; for `cross-page`, of two articles or more;
- name only sections that exist **at the pinned commit**: the article is read from the cache,
  must be selected by the project's docs paths, and its heading path must be one of the chunks the
  importer's own parser and chunker (`parse_article`, `MarkdownChunker` with no settings, which
  cuts at every heading) cut it into. So a case can only name a section ExactDocs produces, and moving the pins (or changing how
  articles are cut) shows every case that no longer holds.

It also checks the review's verdicts, `review.yaml` beside the case files
([Reviewing the golden set](#reviewing-the-golden-set)): a `correct` or `fixed` case is in the set
and a `removed` one is not, no case is reviewed twice, a wrong case names its problems and says
why, and every kind of every project has the sample's number of entries.

It prints every broken case (`<case>: <problem>`, with the closest existing sections when only
the heading path is wrong) and exits with 1. `uv run pytest` checks the rules on the real files
in CI; the section check needs the cache, so it runs in pytest only where the cache already holds
the commits (CI skips it), and with `just golden-validate`.

### Adding a case

1. Pick the project and version, and read the page at the pinned commit, e.g.
   `git -C ~/.cache/exactdocs/golden/zod.git show v4.6.7:packages/docs/content/api.mdx` (the
   cache tags each pinned commit with its version name).
2. Write the case in `cases/<project>.yaml` as above. Start the name with `<project>
   <version>: ` and quote the question. Write `inputs` in block style: a question with `[`, `]`,
   `,`, `?` or `: ` breaks a `{...}` flow mapping, and a reference containing `: ` needs quotes or
   `>-`.
3. Take the heading path from the source: the headings from the top one down to the section, as
   plain text (no backticks or links). Text before the first heading has the path `[]`.
4. Run `just golden-validate --projects <project>`. A wrong path lists the closest sections the
   article has; copy the right one.
5. Check the facts against the page once more: each must be stated there, at that version.

Pitfalls the corpus shows:

- **No H1**: many pages put their title in front matter (Zod v4, TanStack Query, Starlette), so
  their heading paths start at the first H2; Zod v3's README starts at H2 too.
- **TanStack Query** pages for Vue, Solid, Svelte and Angular hold only the code that replaces the
  React page's examples on the website (front matter `ref:`); the prose is only on the React page,
  so name the React page. Its API reference pages have no headings: one section, `[]`.
- **Zod v4 MDX**: a JSX tag on its own line (`</Tab>`) directly before a code fence, and MDX
  comments `{/* ... */}` around fences, make CommonMark pair the fences wrongly, so some real
  headings come out as code (`## The error param` in `error-customization.mdx`). Such a section
  cannot be named until the importer handles it; the validation refuses it, and the ingestion
  benchmark counts such headings in `headings_missed`.
- **Pydantic v1.10** pulls its code examples in with `{!.tmp_examples/...!}`: the code is not in
  the imported text, only the prose is. Its v2 API pages (`docs/api/`) are mkdocstrings stubs.
- **Unanswerable** means the pinned docs do not answer it at all: search the whole docs tree at
  that commit (`git grep`) before writing one; a third-party page that mentions the name is enough
  to make it answerable.

### Reviewing the golden set

Agents wrote and checked the cases, so a sample of them is reviewed independently (#490); the
result is on [Golden set](benchmark/golden-set.md#the-independent-review).

```bash
just golden-review sample              # draw the sample, write reports/golden-review/sheet.md
just golden-review sample --seed 7 --per-stratum 5 --no-text
just golden-review checks              # whole-set checks: reports/golden-review/checks.md, .json
just golden-review summary             # the recorded review's verdicts and error rate
```

`sample` draws `--per-stratum` cases (3 by default) of every kind in every project, at random
with `--seed` (490 by default): each stratum is drawn with its own generator, from its cases in
name order, so the same seed and cases give the same sample. It writes a sheet with, per case, the
question, version, kind, reference answer, facts and sections, each linked to the source at the
pinned commit; with the cache (the default) also the text of each expected section, the sections
of that version closest to the question and reference, and the same section and the closest ones
in the neighbouring versions. `review-draft.yaml` lists the sampled cases with the verdict left
blank.

The verdicts go in `packages/exactdocs/evals/golden/review.yaml`:

```yaml
sample: {seed: 490, per_stratum: 3, drawn_from: 'sha256:39f6f9d5e909d128'}
entries:
- case: 'zod v4.6.7: Is there a util ...'
  project: zod
  kind: identifier-lookup        # the stratum it was drawn from; a fix may change the case's kind
  verdict: fixed                 # correct, fixed (the case was corrected) or removed
  problems: [unsupported-fact]   # empty when correct
  reviewer: independent review agent (adversarial brief; not the agent that wrote the cases)
  date: 2026-11-23
  note: The source line that proves the defect, and what was changed.
```

`drawn_from` is the golden set's fingerprint when the sample was drawn, before any fix: fixes change
the cases' sections and kinds, so drawing again from today's set gives another sample. A fix that
rewrites a question renames the case; its entry names the new case and keeps the old name in `was`.

The problem categories:

| Problem | The case |
|---|---|
| `unsupported-fact` | lists a fact the expected sections do not state at that version, or only imply |
| `wrong-reference` | has a reference answer that is wrong or incomplete for that version |
| `missing-section` | leaves out another section of that version that answers it as well |
| `wrong-section` | names a section that does not answer it |
| `wrong-kind` | has the wrong kind; `cross-page` when one article states every fact |
| `answerable` | is `unanswerable`, but its version's docs answer it |
| `not-a-change` | is a `version-change` whose change the neighbouring versions contradict |
| `ambiguous` | has more than one fair answer, or none without guessing |
| `duplicate` | asks what another case asks of the same version |

`checks` runs over the whole set and needs the cache. It cuts every article of every pinned version
as the importer does (every heading starts a section) and compares words: lower-case, stemmed,
stop words left out, each weighted by its inverse document frequency in that version.

- **Lexical overlap**, per answerable case: the weighted share of the question's words its best
  expected section holds, the same for the best section that is not expected, the expected
  section's rank among all sections of the version, and the longest run of words the question
  shares with an expected section. A run of 5 words or more, 3 of them content words, is listed as
  copied. A question written from its section's words would favour keyword search (BM25).
- **Near-duplicate questions**: pairs of one project that share at least half their content words
  (Jaccard), same version or not.
- **The vocabulary of every `unanswerable` case**: its words no section of its version holds, and
  the three sections holding most of them; one section with 75% of the weighted words is flagged
  to check by hand. Synonyms are not searched; the reviewer does that.

The tests (`tests/evals/test_golden_review.py`, `golden_review.feature`) run on a tiny local
repository; one checks the recorded `review.yaml` against the real case files in CI.

## The ingestion benchmark

Retrieval can only return what ingestion produced. The ingestion benchmark (#346) measures what
the importer makes of the golden corpus under several chunking configurations, and the BM25 recall
each one leads to. It needs no model.

```bash
just ingestion-bench --offline                      # every configuration, every project
just ingestion-bench --configs default,h2 --projects zod
just ingestion-bench --out packages/exactdocs/evals/results   # refresh the recorded run
just ingestion-bench --offline --check              # fail when something got worse than the recorded run
```

For each configuration it imports every pinned version with the real importer into its own
model-free instance (the same path as `golden-import`, with the library's chunking settings set
first), reads back the chunks the importer stored, and compares them with the source at the pinned
commit. Then it runs the whole golden set through BM25, each question in its project's library.
It writes `ingestion.json` and `ingestion.md` to `reports/evals/` (or `--out`) and prints the
summary. The whole corpus takes about a minute per configuration.

The recorded run is in
[`packages/exactdocs/evals/results/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/results)
(`reports/` is not committed). `--check` compares a run with it: in every configuration both
measured, coverage may not drop, the integrity and heading counts (`articles_without_chunks`,
`cuts_in_*`, `lost_chars`, `empty_heading_paths`, `wrong_heading_paths`, `headings_missed`,
`headings_extra`) may not rise, and BM25 recall@5 may not drop more than 2 points. A run on
another golden set (another fingerprint) or other projects fails until the run is recorded again.
When a change to the importer improves the numbers, record the run in the same pull request.

Like the retrieval eval, it runs on releases, not on pull requests: the release workflow's
*Retrieval eval* job runs `--check` (step *Ingestion benchmark*) and a regression stops the
release. If you change the parser, the chunker or the import path, run `just ingestion-bench
--offline --check` before you open the pull request. Pull request CI only runs the benchmark's
quick tests (`tests/evals/test_ingestion.py`, `ingestion_bench.feature`) on a tiny local corpus.

### Configurations

| Name | Settings | What it does |
|---|---|---|
| `default` | split level 3, `max_chars` 4,000 | today's default (#381): `#` to `###` start a chunk; a longer one is cut again at deeper headings |
| `h6` | split level 6, no merging, no bound | every heading starts a chunk (the default before #381) |
| `h2` | split level 2, no bound | only `#` and `##` start a chunk; deeper sections stay inside their parent |
| `merge-400` | split level 6, `min_chars` 400, `max_chars` 4,000 | every heading starts a chunk, then a chunk under 400 characters is merged with the next while the result stays within 4,000 |

They are `CONFIGURATIONS` in `retrieval_eval/ingestion_cli.py`. `default` is whatever a new
library gets, so it follows the shipped default; the others name every setting. When the default
changed in #381, `h3-max-4000` became `default` and the old `default` became `h6`: the ingestion
run was measured again (the same numbers under the new names) and the retrieval run relabelled.
The section ceiling of #141
(splitting a long section at block boundaries) is not one of them yet: it is not exposed in the
library settings.

### Metrics

Each metric is reported per project and version, and in total per configuration. The checks of
block structure use the benchmark's own line reader, not the importer's parser: where the parser
reads a fence, a heading or an indented block differently (MDX, MkDocs), the two disagree and the
disagreement is counted. The reader knows fenced code (backticks or tildes, closed by the same
marker at least as long), ATX and setext headings, pipe-table rows and list items; it does not
know HTML blocks, MDX or indented code, on purpose.

| Metric | Definition |
|---|---|
| `coverage` | share of the golden set's distinct expected sections that start at least one chunk: a chunk's heading path is the section's. `missing_sections` lists every other one, marked `(held)` when it is still a heading inside a bigger chunk; `held_sections` counts those that start a chunk or are held |
| `cuts_in_code_fence` | chunks that end inside a fenced code block (the line reader, fed the article's chunks in order, is inside a fence after the chunk) |
| `cuts_in_table`, `cuts_in_list` | chunks whose last line and the next chunk's first line are both table rows, or both belong to a list |
| `lost_chars` of `source_chars` | non-whitespace characters of the source (the file at the pinned commit, a symlink followed one hop as a reader of the repository sees it, front matter left out) that are in no chunk; each chunk is looked for verbatim after the previous one's match |
| `tokens_p50`, `tokens_p95`, `tokens_max` | chunk size in estimated tokens, `ceil(characters / 4)` (retrieval's `CHARS_PER_TOKEN`); nearest-rank percentiles |
| `small_chunks`, `small_share` | chunks under 50 tokens (`MIN_USEFUL_TOKENS`, about a heading and a sentence or two) |
| `multi_top_chunks`, `multi_top_share` | chunks holding more than one top-level heading (a heading whose path has one element: the H1, or the H2s of a page without H1) |
| `empty_heading_paths` | chunks with an empty heading path: text before the first heading, or an article with no heading |
| `wrong_heading_paths` | chunks whose heading path holds an empty heading or markup that should have become plain text: `{#id}`, `[#id]`, `[text][ref]`, `[text](url)`, `{/*`, `{!` (not an HTML tag: a heading's code span may hold one); examples in `wrong_heading_examples` |
| `headings_missed`, `headings_extra` | per article, how many fewer (more) headings the chunks record than the line reader finds outside fenced code, summed |
| `articles_without_chunks` | selected files the importer stored no chunk for |
| `articles_without_h1` | readable, non-empty files with no level-1 heading |
| `unexpanded_includes` | chunks holding an include the docs build expands and Markdown does not (`{!file!}`, `--8<--`) |
| `mkdocs_blocks_as_code` | MkDocs admonitions and content tabs (`!!!`, `???`, `===`) whose 4-space-indented body Markdown reads as an indented code block |

`examples` keeps up to ten article keys (`<project> <version>:<path>`) per article-level metric.
Next to them, per configuration, `bm25` holds recall@1/5/10, MRR, the wrong-version rate and the
misses of the golden set's answerable cases, with the suite's own evaluators.

**Matching a hit across chunking depths.** A configuration that cuts coarser or finer than the
golden set's sections would otherwise lose every hit to a heading path that no longer exists. So a
returned chunk of the expected version and article answers the expected section when its heading
path is the expected one; or the expected path is a non-empty prefix of it (a finer cut: the chunk
is part of the section); or its path is a prefix of the expected one and the chunk holds the
expected heading (a coarser cut merged the section into it). `recall_at_5_exact` is recall@5 with
only the exact heading path, for comparison. The rule is `golden_run.nested_match`.

### The JSON report

`ingestion.json` is the source the published results (#349) are built from; its layout is stable
and `schema_version` changes when a field is renamed or removed.

- `schema_version`, `golden` (the golden set's fingerprint), `cases`, `projects`,
  `min_useful_tokens`, `chars_per_token`;
- `configurations`: one entry per configuration with `name`, `about`, `chunking` (the library
  settings: `split_level`, `min_chars`, `max_chars`, `chunker`), `totals` (the metrics above over
  the whole corpus), `bm25` (`answerable`, `recall_at_1`, `recall_at_5`, `recall_at_10`, `mrr`,
  `recall_at_5_exact`, `wrong_version_rate`, `misses`, `errors`) and `versions` (per `project` and
  `version`: `library`, `commit` and the same `metrics`).

### Running more retrieval modes on the golden set

`retrieval_eval/golden_run.py` is the golden set's multi-library runner: `golden_retriever` sends
each question to its project's library through the suite's `SearchDocsRetriever`, and
`run_golden` scores the whole set with the suite's evaluators and `evaluate_mode`, with the exact
or the nested match rule. The ingestion benchmark runs BM25 through it, and the retrieval
benchmark (below) every mode.

## The retrieval benchmark

The retrieval benchmark (#347) runs every retrieval configuration ExactDocs offers on the golden
set, at every chunking configuration of the ingestion benchmark, and names the configuration to use
by default for each budget: no models, local models only, hosted models.

```bash
just retrieval-bench --offline --configs bm25          # the model-free part: about a minute per chunking
just retrieval-bench --offline                          # + every local model that was pulled (hours, below)
just retrieval-bench --configs 'bm25*,hybrid:bge-small*' --chunkings default,h2 --projects zod
just retrieval-bench --out packages/exactdocs/evals/results    # refresh the recorded run
just retrieval-bench --configs bm25 --chunkings default --check   # what the release runs
```

For each chunking configuration it imports every pinned version once, into a model-free instance
of its own (the ingestion benchmark's import). Then every configuration runs on that data
directory in a container built with only the model roles it calls, embeds the corpus the first
time an embedding model is used (as the `embed` jobs would, timed and costed as `index`), and asks
every golden question in its project's library (`golden_run`), one at a time. Hits are matched
with the nested rule, so a coarser or finer chunking is not penalised for cutting at another depth.
It writes `retrieval.json` and `retrieval.md` to `reports/evals/` (or `--out`), prints the summary
(and appends it to `$GITHUB_STEP_SUMMARY`), and exits with 1 when a configuration returned a result
of another version, read outside its version (agentic traces), or failed on a question.

### The matrix

| Configuration | Budget | Models |
|---|---|---|
| `bm25` | none | none |
| `bm25+ce` | local | the local cross-encoder (`Xenova/ms-marco-MiniLM-L-6-v2`, timeout 30 s) |
| `hybrid:<model>`, `hybrid:<model>+ce` | local | a local embedding model (default: `BAAI/bge-small-en-v1.5`, `snowflake/snowflake-arctic-embed-s`, `BAAI/bge-base-en-v1.5`; `--local-embeddings`), and the cross-encoder |
| `hybrid:hosted`, `hybrid:hosted+ce` | hosted | the embedding model `EXACTDOCS_AI__EMBEDDING__MODEL` names (and the local cross-encoder) |
| `<base>+judge` for each base above | hosted | the LLM judge, `EXACTDOCS_AI__JUDGE__MODEL` (else the `llm` role) |
| `hyde:hosted` | hosted | the hosted embedding model and `EXACTDOCS_AI__LLM__MODEL` |
| `agentic:hosted` | hosted | `EXACTDOCS_AI__LLM__MODEL` |

Each runs at every chunking configuration (`default`, `h6`, `h2`, `merge-400`;
`--chunkings`). `--configs` takes names or shell patterns (`'hybrid:*+ce'`). A configuration that
cannot run is listed with the reason: a local model that was not pulled (`unavailable`, with the
`exactdocs models pull` command), a hosted role that is not configured, or a hosted configuration
without `--allow-providers` (`skipped`). The section ceiling of #141 (`max_section_chars`, 8,000
characters) applies to every configuration, but it is not a library setting, so it cannot be
swept per configuration yet; nor can the ways to embed a chunk longer than the embedding model's
window (bge-small reads about its first 1,800 characters), which have no setting either.
`<pattern>@<chunking>` runs a configuration at some chunkings only (`'*+ce@default'`).

### Metrics

Each metric is reported per configuration and chunking, over all cases, per question kind
(`by_kind`) and per project (`by_project`).

| Metric | Over | Definition |
|---|---|---|
| recall@1, recall@5, recall@10 | answerable cases | the first expected section is in the top k |
| MRR | answerable cases | mean of 1 / the rank of the first expected section (0 past 10) |
| section recall@5, @10 | answerable cases | the share of a case's expected sections in the top k, averaged over the cases |
| nDCG@10 | answerable cases | binary relevance over every expected section, below |
| wrong-version rate | every case | share of cases with a result of another version (read back by chunk ID, as in the suite); must be 0 |
| unanswerable clean | unanswerable cases | share that returned nothing of another version |
| no answer | unanswerable cases | share that signalled no answer: came back with no result |
| answerable empty | answerable cases | share that came back with no result (a "no answer" that was wrong) |
| p50 / p95 latency | every case | nearest-rank percentiles of the search alone, one question at a time, on the machine named in the report |
| tokens / USD per question | every case | what the spend ledger grew by during each search (an embedding, a judgment, a HyDE answer, an agent run); USD from the configured prices or `genai-prices` |
| index | per embedding model and chunking | seconds, tokens and USD of embedding the whole corpus once |

**nDCG@10.** A returned hit at rank *i* is relevant (*rel* = 1) when it answers an expected section
that no earlier hit answered, so a section found twice counts once; otherwise *rel* = 0.
DCG@10 = Σ<sub>i=1..10</sub> *rel*<sub>i</sub> / log<sub>2</sub>(*i* + 1). The ideal DCG puts every
expected section first: IDCG@10 = Σ<sub>i=1..min(R, 10)</sub> 1 / log<sub>2</sub>(*i* + 1), with *R*
the number of expected sections. nDCG@10 = DCG@10 / IDCG@10.

**Cases with several expected sections** (`cross-page`, and any case listing more than one).
recall@k and MRR follow the suite's rule and the fixture suite's numbers: they count the first
expected section only (`VersionAndRank`, `rank_of`), so they stay comparable with the retrieval
eval and the ingestion benchmark. Section recall@k counts every expected section: a case scores
the share of its sections found in the top k (each found section counted once, by the hit
matching rule above), and the metric is the mean over cases; for a case with one section it equals
recall@k. The per-kind and per-project tables show recall@5, section recall@5 and nDCG@10 side by
side, so the `cross-page` row says how often the whole answer came back, not only its first page.

**"No answer".** `search_docs` has no explicit no-answer signal: a result carries a `score` that is
"only comparable within one search", and no mode applies a relevance threshold. The only signal a
caller can read is an empty result list. BM25 returns nothing only when no term of the question is
in the version; `hybrid` always returns the nearest chunks; the cross-encoder and the judge reorder
and never drop; `agentic` answers with the chunks the agent picks. The benchmark counts an empty
result as "signalled no answer", and reports how often an answerable case came back empty too, so
a configuration that returns nothing more often is not rewarded for it. In the recorded run no
configuration signalled no answer for any of the 54 unanswerable cases (0%), while all of them
returned nothing of another version: a caller cannot tell an unanswerable question from an
answerable one by the result list today.

### The recommendation

For each budget, cheapest first, the candidates are the results that ran with no wrong version,
no read outside the version, no error and no reranker fallback. The best of a budget, by recall@5,
then nDCG@10, MRR, lower USD and lower p95, becomes its default only when its recall@5 beats the
cheaper budget's default by 5 points (the suite's `DEFAULT_MARGIN_POINTS`); otherwise the cheaper
default stays, and the reason says by how much the dearer one fell short. Each recommendation
gives its USD per 1000 questions and its numbers. A budget nothing of which ran is "not measured
yet"; for hosted models that means a real-providers run is needed.

### Reproducing a result

`retrieval.json` (`schema_version` 1, read by #349) records, besides the metrics:

- `golden` (the golden set's fingerprint), `cases`, `projects`, and `corpus`: every pinned version
  as `project`, `version`, `commit`;
- `environment`: the ExactDocs commit (`-dirty` with uncommitted changes), Python, platform, CPU
  count, and the versions of `exactdocs`, `fastembed`, `onnxruntime`, `pydantic-ai-slim` and
  `pydantic-evals`;
- `chunkings`: each chunking configuration's name and library settings;
- per result (`results`): `configuration`, `chunking`, `budget`, `mode`, `rerank`, `status` and
  `reason`; `models` (each role's `<profile>:<model>`, the profile's `kind` and `base_url`, and for
  a local model the Hub `revision` it was pulled at and its `dimensions`); `settings` (the `ai`
  settings it ran with: the roles, `rerank_with`, the reranker's `top_n` and timeout, the judge's
  timeout, HyDE and agentic limits; never a key); `metrics`, `by_kind`, `by_project`, `index`,
  `fallbacks`, `reranked`, `rerank_fallbacks`, `misses`, `errors`, `wrong_version_cases`,
  `left_version_cases`;
- `recommendations`: per `budget`, the `configuration`, `chunking`, `usd_per_1000_questions` and
  the `reasons`.

The recorded run is `packages/exactdocs/evals/results/retrieval.json` and `retrieval.md`.
`schema_version` changes when a field is renamed or removed.

### The recorded run

Measured on an Apple M-series laptop (10 cores) with no network, on the whole golden set, in about
1 h 40 min. A full local matrix (three embedding models, each with and without the cross-encoder,
at four chunkings) would take about six hours on that CPU, so it ran on this subset:

- `bm25` and `hybrid:bge-small-en-v1.5` at every chunking configuration;
- `bm25+ce` at `h6` and `h2`; `hybrid:bge-small-en-v1.5+ce` at `h6`;
- `hybrid:snowflake-arctic-embed-s` at `h6` (the second local embedding model);
- `hybrid:bge-base-en-v1.5` did not run (about 50 minutes of embedding per chunking there);
- every hosted configuration is listed as skipped: it needs a real-providers run.

```bash
EXACTDOCS_MODELS_DIR=~/.cache/exactdocs/models just retrieval-bench --offline \
  --configs 'bm25,hybrid:bge-small-en-v1.5,bm25+ce@h6,bm25+ce@h2,hybrid:bge-small-en-v1.5+ce@h6,hybrid:snowflake-arctic-embed-s@h6,*+judge,*:hosted*' \
  --out packages/exactdocs/evals/results
```

The run predates #381, so its `default` was today's `h6`; the report was relabelled when the
default changed (the commands above name today's chunkings). Embedding the whole corpus took 17
minutes with bge-small at `h6` (8 at `h2`, 13 at `default`, 11 at `merge-400`) and 16 with
arctic-embed-s; the cross-encoder adds about 1.4 s per question (32 candidates). What it found:
BM25 is best at `default`, split level 3 and 4,000 characters (recall@5 81.7%, against 79.8% at
`h6`), which #381 made the default for new libraries; hybrid on bge-small reaches 84.6% at `h6`,
3 points more, under the 5-point margin, so BM25 stays the default for both the no-model and the
local budget; the cross-encoder adds as much as hybrid at `h6` and loses recall at `h2`, whose
chunks are longer than its window; arctic-embed-s is below BM25 (75.3%).

### Running it with local models

```bash
EXACTDOCS_MODELS_DIR=~/.cache/exactdocs/models uv run exactdocs models pull \
  BAAI/bge-small-en-v1.5 Xenova/ms-marco-MiniLM-L-6-v2 \
  snowflake/snowflake-arctic-embed-s BAAI/bge-base-en-v1.5
EXACTDOCS_MODELS_DIR=~/.cache/exactdocs/models just retrieval-bench --offline
```

The pull is the only step that needs the network; the models then run on the CPU (ONNX Runtime,
half the cores per call). Embedding the corpus dominates the run time (`index` seconds per model
and chunking in the report), then the cross-encoder; see the recorded run above.

### Running the hosted part

Only by hand, never in CI: the manual *Retrieval eval (real providers)* workflow
(`.github/workflows/eval-providers.yml`) with the input `benchmark` ticked runs the job *Retrieval
benchmark with real providers*: it configures profile `eval` from the same repository variables as
the suite (`EVAL_PROVIDER_KIND`, `EVAL_PROVIDER_BASE_URL`, `EVAL_PROVIDER_API_VERSION`,
`EVAL_EMBEDDING_MODEL`, `EVAL_LLM_MODEL`, `EVAL_JUDGE_MODEL`, secret `EVAL_PROVIDER_API_KEY`),
pulls the local models, and runs `--allow-providers` on `benchmark_configs` (default
`bm25,*+judge,*:hosted*`) with `benchmark_args` (e.g. `--chunkings default`). The report is the
artifact `retrieval-bench-providers`. Locally the same is one command with the roles in the
environment:

```bash
EXACTDOCS_AI__PROVIDERS__EVAL__KIND=openai EXACTDOCS_AI__PROVIDERS__EVAL__API_KEY=... \
EXACTDOCS_AI__EMBEDDING__MODEL=eval:text-embedding-3-small EXACTDOCS_AI__LLM__MODEL=eval:gpt-4.1-mini \
just retrieval-bench --allow-providers --configs 'bm25,*+judge,*:hosted*'
```

The tests run the hosted part on stand-ins only (`tests/evals/test_retrieval_bench.py`, marked
`eval`, and `retrieval_bench.feature`): the term-hash embedding and one `FunctionModel` that rates as
the judge, writes for HyDE and browses as the agent, priced. They check the plumbing, the wrong-version
rate of 0 and that cost reaches the report; their numbers are never results.

### When it runs

On releases, the *Retrieval eval* job runs BM25 at the `default` chunking through the benchmark
(step *Retrieval benchmark*, about a minute) with `--check`: it fails on a wrong version, an error,
or recall@5 or nDCG@10 more than 2 points below the recorded run (the same golden set and projects
are required). The local and hosted parts never run in CI; refresh the recorded run by hand when
ranking, chunking or a model changes. Pull request CI runs the quick tests only.

## The agent benchmark

Retrieval numbers do not show that a coding agent reaches the right answer. The agent benchmark
(#348) measures that: a [pydantic-ai](https://ai.pydantic.dev/) agent whose only documentation
is ExactDocs answers the golden-set questions, and an LLM judge grades each answer against the
case's reference answer and facts. It lives in
[`packages/exactdocs/evals/agent_bench/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/agent_bench)
and never runs in CI with a model: locally, or from the manual *Agent benchmark (real providers)*
workflow.

### How a run works

For each retrieval configuration, the projects of the asked cases are imported with the real
importer at their pinned commits (as `golden-import` does), and embedded when the configuration
names an embedding model. Configurations that share an embedding model share one import. Then
ExactDocs is started **as shipped**, `exactdocs serve --stdio` on that data directory with the
configuration's settings, and each agent model answers every case through a pydantic-ai
`MCPToolset` on that server. The agent has no other tool.

What the agent is told is what a coding agent knows from a project, never the answer:

- the instructions, the same for every model: its only documentation source is the ExactDocs
  tools; find the library, search exactly the version the project uses, read what it needs, answer
  briefly from what it read, and say so when that version's documentation does not cover the
  question instead of answering from memory or another version;
- the prompt: `My project uses <project title> at version <version>.` and the question. The
  ExactDocs library ID is not given: finding it (`list_libraries`, `resolve-library-id`) is part
  of the task.

Both are recorded in the report (`meta.agent_instructions`, `meta.prompt`).

A `process_tool_call` hook records, per question: every tool call (name, arguments cut to 200
characters, time, error), the sections read in full (`read_chunk`, the chunks `query-docs`
returned, whole articles from `read_article`) with their version, and how each search was
answered (`bm25`, or `bm25 (mode_unavailable)` when the server fell back). The run also records
the input and output tokens over every model request, the USD from ExactDocs' own price list
(`GenaiPrices`, the bundled `genai-prices` data; `unpriced` when the model is not in it, as for
the stand-ins), and the wall time. A run that hits the request limit (`--max-requests`, default
20) or a provider error keeps its record with the error and is graded wrong.

### The judge

The judge is a pydantic-ai agent with a typed output (grade, `wrong_version`, reason), run as a
Pydantic Evals evaluator. It gets the question, the version, the kind, the reference answer, the
facts and the answer as JSON, not the documentation, and grades:

| Grade | When |
|---|---|
| `correct` | every required fact, in any wording, and nothing the reference contradicts |
| `partially_correct` | some of the facts, nothing contradicted |
| `wrong` | none of them, something the reference contradicts, or an invented API or behaviour |
| `refused` | says the documentation does not cover it, or declines, and states no facts |

For an `unanswerable` case, the judge grades an answer that says the documentation of that version
does not cover it `refused`, and one that answers anyway (from another version, from memory,
invented) `wrong`. The report counts `refused` as accurate for an `unanswerable` case only: there
it is the right answer, for any other kind it is a miss. Each question keeps its raw grade.
`wrong_version` is set when the answer states something true of another version only; the report
counts those separately (*Wrong for the version*). Its instructions are in
`agent_bench/judge.py`.

### The report

`reports/evals/agent-bench.json` (and `.md` next to it, also appended to `$GITHUB_STEP_SUMMARY`),
one cell per agent model and retrieval configuration:

- grades and accuracy (share `correct`, plus `refused` on `unanswerable` cases), overall, per kind
  and per project; errors;
- *Wrong for the version*: answers the judge flagged `wrong_version`;
- *Read the answer*: of the answerable questions, the share where the agent read in full every
  section the case names (at its version). Search snippets do not count. This is the measure of
  "the cited chunks contain the required facts": a case's sections are, by construction, where
  its facts are stated;
- *Read another version*: questions where the agent read something of the asked library at
  another version;
- tool calls, tokens and USD per question, median wall time, and how the searches were answered.

`meta` holds what a rerun needs: the agent models, the judge model, each configuration's
settings, the limits, the instructions and prompt, the ExactDocs version and repository commit,
and every imported version with its pinned and recorded commit. `questions` holds every question's
record (tool calls, chunks read as `<chunk ID>@<version>`, tokens, USD, answer, judge's reason).

### Running it

```bash
just agent-bench run --offline --projects starlette,zod --limit 4   # stand-ins, no provider
just agent-bench run \
  --agent-model openai:gpt-5-mini --agent-model anthropic:claude-sonnet-4-5 \
  --judge-model openai:gpt-5 \
  --retrieval bm25:mode=bm25 \
  --retrieval 'hybrid:mode=hybrid,embedding.model=eval:text-embedding-3-small'
just agent-bench run --help
```

- `--agent-model` (repeat for several) and `--judge-model` are
  [pydantic-ai model names](https://ai.pydantic.dev/models/overview/) (`<provider>:<model>`); the
  provider's usual variables give the key (`OPENAI_API_KEY`, `OPENAI_BASE_URL` for a gateway,
  `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`). Use a judge from another vendor than the agents where
  you can.
- `--retrieval name[:key=value,...]` (repeat for several) names one configuration: each key is
  an ExactDocs AI setting path set as `EXACTDOCS_AI__<KEY>` (`mode=hybrid` is
  `EXACTDOCS_AI__MODE=hybrid`, `embedding.model=eval:...` is `EXACTDOCS_AI__EMBEDDING__MODEL`),
  on top of the environment, for both the import and the server. Profiles (`eval:` above) come
  from the environment as for any instance (`EXACTDOCS_AI__PROVIDERS__EVAL__...`). The default is
  `bm25:mode=bm25` and `hybrid:mode=hybrid`; without an embedding model the second falls back to
  BM25, which the report shows. The configurations of the retrieval benchmark (#347) are written
  the same way.
- `--projects`, `--kinds`, `--limit N` (cases per project) pick the cases; `--concurrency`
  asks several questions at once (wall time then includes contention); `--work-dir` keeps the
  data directories and each server's log (`server-<configuration>.log`).
- `--offline` uses the stand-ins in `agent_bench/offline.py` (pydantic-ai `FunctionModel`s):
  `offline:search` answers from the search snippets, `offline:read` reads the top section first,
  and the judge grades by word overlap with the facts. They prove the plumbing, not quality.

The manual workflow *Agent benchmark (real providers)* (`.github/workflows/agent-bench.yml`,
`workflow_dispatch` only, environment `eval-providers`) runs the same command. Its inputs are
`agent_models` (comma-separated), `judge_model`, `retrieval` (configurations separated by spaces)
and `args` (e.g. `--projects zod --limit 10`). Keys: the secrets `AGENT_BENCH_OPENAI_API_KEY`,
`AGENT_BENCH_ANTHROPIC_API_KEY`, `AGENT_BENCH_GOOGLE_API_KEY` (and the variable
`AGENT_BENCH_OPENAI_BASE_URL` for an OpenAI-compatible gateway) for the agents and the judge; the
`eval` profile of the retrieval workflow (`EVAL_PROVIDER_*`) for the server's models. The report
is uploaded as the artifact `agent-bench`.

### Judge agreement

The judge is checked against people: at least 50 answers labelled by hand, and the share where the
judge gave the same grade.

```bash
just agent-bench sample --report reports/evals/agent-bench.json --size 50   # -> agent-bench-labels.yaml
# fill in `grade` and `wrong_version` (true/false) for each answer
just agent-bench agreement --report reports/evals/agent-bench.json --labels reports/evals/agent-bench-labels.yaml
```

`sample` picks answers reproducibly (`--seed`) and writes each with its question, version, kind,
reference and facts, and blank labels; the judge's grade is left out so it cannot steer the
labeller. Label with the judge's grades, which the file's header repeats:

- `correct`: states every fact, nothing the reference contradicts;
- `partially_correct`: states some of the facts, nothing contradicted;
- `wrong`: states none, contradicts the reference, or invents an API or behaviour;
- `refused`: says the documentation does not cover it (or declines) and states no facts.

For an `unanswerable` case, an answer saying the documentation does not cover it is labelled
`refused`, not `correct` (the report counts it as right for that kind); answering anyway is
`wrong`. `agreement` prints how many answers were labelled, how many the judge graded the same
(`rate`), the same for `wrong_version`, and a confusion table (hand grade to judge grades).
Entries left blank are skipped. Label answers from a real-model run: the stand-ins' answers are
not worth labelling.

### Tests

`tests/evals/test_agent_bench.py`: the recording, grounding, pricing, the stand-in judge, the
judge evaluator, the report and agreement run in CI. The end-to-end test, marked `eval`
(`uv run pytest -m eval`), imports a two-version corpus built in a temporary repository, starts
`exactdocs serve --stdio` on it under two configurations and runs both stand-in agents and the
stand-in judge through it.

## Tiers

| Tier | Modes | Where they run for real |
|---|---|---|
| release (gating) | `bm25` | the release's *Retrieval eval* job, before anything is published: step *Retrieval eval (BM25 gating, hybrid on term-hash)* on SQLite, and step *Retrieval eval on pg_search (BM25, gating)* on ParadeDB's BM25 (#104), both against the tagged tree's `baseline.json`, with `--expect-engine pg_search` so a fallback to PostgreSQL full-text search fails it; no model. The suite runs on the database `EXACTDOCS_DATABASE_URL` names, so `EXACTDOCS_DATABASE_URL=postgresql+psycopg://.../<empty database> EXACTDOCS_SECRET_KEY=... just eval` runs it on PostgreSQL by hand |
| local (report-only) | `hybrid`, with rerank when a reranker is configured | at every release in the SQLite step on the term-hash stand-in (`--offline-embedding`): its wrong-version rate must be 0, its recall is not a measure of hybrid. With real models: the last steps of the same job (#245), with the `[local]` extra and the default models cached between releases, no secret: `bm25` and `hybrid` on `BAAI/bge-small-en-v1.5`, then both reranked by `Xenova/ms-marco-MiniLM-L-6-v2` (reranker timeout raised to 30 s so every rerank is measured), compared with the tagged tree's baseline. These steps never stop a release (`continue-on-error`); their summary marks `default-eligible` |
| provider | `hybrid_hyde`, `agentic`, and any mode reranked by the LLM judge | in tests with pydantic-ai's `TestModel` / `FunctionModel` (`hybrid_hyde`: `tests/evals/`, `run_on_fixture` with `offline_hyde_container`, the term-hash embedding and a priced stand-in LLM, `llm` in `local_roles`: wrong-version rate 0, and its tokens and USD reach `tokens_per_question` / `usd_per_question`; `agentic`: `test_agentic_is_evaluated_on_a_scripted_model_and_stays_in_the_version` runs the whole suite through the real pipeline, Code Mode and limits on a scripted `FunctionModel` in the release's *Retrieval eval* job (`pytest -m eval`), and fails on any wrong-version answer or any read outside the version in a run's trace); with a real provider only by hand: `just eval --configured-models --allow-providers`, or the manual *Retrieval eval (real providers)* workflow (`.github/workflows/eval-providers.yml`, `workflow_dispatch` only), which configures profile `eval` from the repository variables `EVAL_PROVIDER_KIND`, `EVAL_PROVIDER_BASE_URL`, `EVAL_PROVIDER_API_VERSION` and `EVAL_<ROLE>_MODEL` and the secret `EVAL_PROVIDER_API_KEY` |

A mode whose model role is not configured is reported as `unavailable`, with the role it lacks.
Whether a configured mode may run is decided **per model role**, not per tier: every role its
search calls (its own, and the reranker when one is configured) must be listed in `--local-roles`,
the roles whose model runs on this machine, or the mode is `skipped` unless `--allow-providers` is
given. So a `hybrid` run on a hosted embedding model is skipped like `agentic` is. No CI or
release run calls a hosted model, and none needs a secret to pass. (Provider profiles exist now
(#241); deriving `--local-roles` from a role's profile kind is a follow-up.)

## Adding a mode

The suite asks for a mode through the same `search_docs` an agent uses (`mode=<name>`), so a new
mode needs no change to the cases or the evaluators:

1. Give it a tier in `MODES` (`retrieval_eval/suite.py`); a test fails until every
   `RetrievalMode` has one.
2. If it reports spend, fill `tokens` and `usd` of the answer in `SearchDocsRetriever`.
3. Run `just eval` with the mode configured, then `--write-baseline` once its numbers are agreed.
