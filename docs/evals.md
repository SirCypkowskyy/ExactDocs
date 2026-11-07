# Retrieval evals

Retrieval modes are compared with numbers before one becomes a default. The eval suite runs one
dataset of questions through every retrieval mode this build can run, on the fixture docs
repository imported for real, and reports per mode how often the right section comes back, how
often anything of another version does, what it cost and how long it took. The decisions behind
it are in [AI retrieval decisions](decisions/ai-retrieval.md#evaluation).

The suite is development and CI tooling: it lives in
[`packages/exactdocs/evals/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals),
outside the package, and [Pydantic Evals](https://ai.pydantic.dev/evals/) (`pydantic-evals`
2.60.0) is in the `dev` dependency group, not in an extra. Nothing of it ships in the wheel or
the image.

## Running it

```bash
just eval                       # every mode; those that cannot run are listed with the reason
just eval --modes bm25          # one mode
just eval --report out.json     # JSON report elsewhere (default: reports/evals/retrieval.json)
just eval --baseline develop.json --ratchet --reference-dataset develop.yaml   # what CI does
just eval --configured-models --local-roles embedding,reranker   # local models from EXACTDOCS_AI__...
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
models instead. `uv run pytest` runs the same BM25 run
(`tests/evals/`), so a ranking change that breaks a gate also fails the tests.

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
| tokens / USD per question | every question | what the models cost; 0 for BM25, and 0 for every mode until the AI modes report their spend |

The version of a result is the version **of its chunk**, not the version the answer names: every
returned chunk ID is read back with `read_chunk`, which serves it from the version the ID was issued
for (chunk IDs hash their version), and its version and commit are compared with the question's. So
a search that lets another version's chunk through fails the suite even when it labels that chunk
with the version asked for. (Today `search_docs` already drops a pipeline's hit of another
version, since it loads chunks from the asked version's manifest only; the eval is the check that
this stays true for every mode and adapter.)

The JSON report also lists, per mode, the cases with a wrong version (and the offending results),
the questions whose section was not in the top 10, the questions that raised, and how many a
cheaper mode answered (`fallbacks`).

## Gates

- **Wrong-version rate must be 0 for every mode that ran**, whatever its recall. One result of
  another version fails the suite.
- **recall@5 may not drop more than 2 points below the baseline** stored on `develop`. A drop fails
  the suite for BM25 and is a warning for the report-only modes. A gating mode with no baseline
  entry is a warning (its recall is then not gated).
- **The stored baseline only moves up** (`--ratchet`, on in CI): the branch's `baseline.json` may
  not store a lower BM25 recall@5 than `develop`'s, and a value it raises must be what the run
  measures (a stored recall@5 above the measured one fails).
- Both compare with `develop`'s baseline only **on the same dataset**; when the dataset changed,
  see [Changing the dataset](#changing-the-dataset).
- A question whose search raises fails the suite.
- **A mode becomes a default only when the suite shows it beats BM25's recall@5 by at least
  5 points with a wrong-version rate of 0.** The report marks such a mode `eligible_as_default`;
  changing the default order (`DEFAULT_MODE_ORDER`) without that is not accepted.

The baseline is `packages/exactdocs/evals/retrieval_eval/baseline.json`: recall@1/5/10, MRR and
the wrong-version rate of each mode that ran (no latency, which depends on the machine), and the
`dataset` fingerprint they were measured on. CI compares with the copy on `develop`, checked out on
its own (that file and `develop`'s `dataset.yaml`), so a pull request cannot lower
the bar it is measured against; a failed checkout fails the job. Only when `develop` has no
`baseline.json` at all does CI compare with the branch's own, with a warning in the summary. A
change that improves ranking refreshes it in the same pull request, where the diff shows the new
numbers:

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
3. In CI, `develop`'s baseline has another fingerprint, so the baseline is **reset**:
    - the drop gate compares with the branch's `baseline.json`, and the ratchet against `develop`
      is off; once the pull request is merged it starts again from the new baseline;
    - the branch's stored recall@5 must be exactly what the run measures, neither above nor below,
      since it becomes the next bar;
    - **`develop`'s dataset is still run**, with the branch's code, and gated against `develop`'s
      baseline as usual (`--reference-dataset`; its summary is *Retrieval eval on the reference
      dataset*). A question of the old dataset whose version or section the fixture no longer has
      fails the run instead of being skipped. So rewording or adding a question cannot hide a
      ranking regression: the old questions still catch it;
    - the reset is reported as a warning annotation on the pull request's checks (*Eval baseline
      reset*) and in the job summary (**Baseline reset: the dataset changed (...)**).

If `baseline.json` was not rewritten, its fingerprint is not the dataset's and CI fails with
"was recorded for dataset ..., not this one".

**The fixture is not part of the fingerprint.** A change to the fixture docs repository
(`packages/exactdocs/tests/fixtures/docs-repo`), such as a new distractor article, is gated like a
ranking change: recall@5 may not drop more than 2 points below `develop`'s baseline, and there is
no reset path (a reset still runs `develop`'s dataset against `develop`'s baseline, on the new
fixture). A fixture change has to keep BM25's recall@5 within those 2 points.

## Tiers

| Tier | Modes | Where they run for real |
|---|---|---|
| every PR (gating) | `bm25` | the *Python* CI job, step *Retrieval eval (BM25, gating)* on SQLite, and step *Retrieval eval on pg_search (BM25, gating)* on ParadeDB's BM25 against the branch's baseline (#104); no model. The suite runs on the database `EXACTDOCS_DATABASE_URL` names, so `EXACTDOCS_DATABASE_URL=postgresql+psycopg://.../<empty database> EXACTDOCS_SECRET_KEY=... just eval` runs it on PostgreSQL by hand |
| local (report-only on PRs) | `hybrid`, with rerank when a reranker is configured | a CI job with the `[local]` extra and cached ONNX models, no secret, compared with the baseline on `develop`; added with the local models (#245) |
| provider | `hybrid_hyde`, `agentic` | in tests with pydantic-ai's `TestModel` / `FunctionModel`; with a real provider only by hand: `just eval --configured-models --allow-providers`, or the manual *Retrieval eval (real providers)* workflow (`.github/workflows/eval-providers.yml`, `workflow_dispatch` only), which configures profile `eval` from the repository variables `EVAL_PROVIDER_KIND`, `EVAL_PROVIDER_BASE_URL`, `EVAL_PROVIDER_API_VERSION` and `EVAL_<ROLE>_MODEL` and the secret `EVAL_PROVIDER_API_KEY` |

A mode whose model role is not configured is reported as `unavailable`, with the role it lacks.
Whether a configured mode may run is decided **per model role**, not per tier: every role its
search calls (its own, and the reranker when one is configured) must be listed in `--local-roles`,
the roles whose model runs on this machine, or the mode is `skipped` unless `--allow-providers` is
given. So a `hybrid` run on a hosted embedding model is skipped like `agentic` is. No CI run in a
pull request calls a hosted model, and none needs a secret to pass. (Provider profiles exist now
(#241); deriving `--local-roles` from a role's profile kind is a follow-up.)

## Adding a mode

The suite asks for a mode through the same `search_docs` an agent uses (`mode=<name>`), so a new
mode needs no change to the cases or the evaluators:

1. Give it a tier in `MODES` (`retrieval_eval/suite.py`); a test fails until every
   `RetrievalMode` has one.
2. If it reports spend, fill `tokens` and `usd` of the answer in `SearchDocsRetriever`.
3. Run `just eval` with the mode configured, then `--write-baseline` once its numbers are agreed.
