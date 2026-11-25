# Context7

!!! abstract "TL;DR"
    - [Context7](https://context7.com) (Upstash) is the documentation MCP most coding agents use.
      It is hosted, so we cannot choose how it indexes, and it serves a library's version only
      when someone added it.
    - The run (#493) asks which of the golden set's pinned versions it serves, and how good its
      answers are for those it does, scored with the [text scorer](text-scoring.md) next to
      ExactDocs' BM25.
    - Nothing has been measured yet.
    - No Context7 number is published until Upstash gives permission in writing
      ([Terms of service](#terms-of-service)).

| Part | Code |
|---|---|
| the run | `retrieval_eval/context7_cli.py` |
| the response reader, coverage, report and Markdown | `retrieval_eval/context7.py` |

```bash
export CONTEXT7_API_KEY=...                       # from context7.com/dashboard; the run refuses to go out without it
just context7-bench                               # every project: one request per golden question
just context7-bench --from-cache                  # score the kept responses again, calling nothing
just context7-bench --projects starlette          # one project
```

It needs the golden corpus cache (`--offline` uses it as it is) and the key.

## What a run does

### The API

- Every request is `GET https://context7.com/api/v2/context?libraryId=&query=&type=json` of the
  Public API 2.0.0 (`API_VERSION`, `info.version` of `https://context7.com/openapi.json`).
- It is sent with `Authorization: Bearer $CONTEXT7_API_KEY`.
- A rate-limited request (429) waits out `Retry-After` (at most 60 s) and is sent again, up to
  five times.

### Coverage

For each pinned version, the first of its questions goes to `/<owner>/<repo>/<version>`: the
project's library from `corpus.yaml` and the pinned tag.

A version Context7 has not indexed is not an error. It serves a matching tag, another release of
the line, or the current docs, and the JSON response's `version` object says which. The run reads
it (`coverage_of`):

| Response | Coverage |
|---|---|
| no `version` object, or `status: verified` | **served** |
| `unverified` with a release in `served` | **unverified** (another release stands in for the pinned one) |
| `unverified` with `served: null`, or 404 `version_not_found` | **not served** |

The coverage table gives, per version:

- the status;
- the library ID Context7 says served it (a library that moved, such as `encode/starlette` to
  `kludex/starlette`, is followed by Context7 itself);
- the release served;
- the date of the answer.

Asking a version Context7 lacks queues it for indexing, so coverage can change between runs.

### The questions

- The other questions of a served or unverified version go to the same pinned ID. The probe's
  answer is its first question's.
- Questions of a version Context7 does not serve go to `/<owner>/<repo>` alone, its current docs,
  which is what an agent gets there.
- The three groups (`pinned`, `unverified`, `latest only`) are scored and reported apart and never
  mix.

### The budget

Context7's API takes no size budget, so each response is cut where ExactDocs' `query-docs` would
stop (`TOKEN_BUDGET`, 10,000 estimated tokens, 4 characters each). The results are kept best first
while their text fits.

### The results

- A response's `codeSnippets` and `infoSnippets` are one list in Context7's `rank` order.
- An info snippet's text is its `content`; a code snippet's is its code blocks, fenced.
- The code snippet's title and description are left out of the text scored. Context7 writes them,
  they are not the docs', and the text scorer would count them as unmatched text.

### Scoring

- Scoring is the text scorer's (`text_row`), with every metric of
  [Metrics of text results](text-scoring.md#metrics-of-text-results) and its interval.
- ExactDocs' BM25 at `default` answers every question in the same run and is scored the same way,
  as in the [Grounded Docs run](grounded-docs.md#what-a-run-does).
- Each group is tested against it on its own cases: McNemar mid-p for recall@1, @5 and @10, the
  sign-flip permutation test for MRR and nDCG@10.
- Each group is also tested against ExactDocs' `bm25` and `hybrid:bge-small-en-v1.5` from
  `results/retrieval.json`, when that run measured the same golden set.

### The cache

- Every answer (200 or 404) is kept as it came, one JSON file per request (`status`, `body`,
  `date`, `ms`), in `--responses` (`reports/evals/context7-responses/`).
- A later run asks only what is not there. `--from-cache` calls nothing and fails on a missing
  response.
- A failed request is not kept, so a rerun asks it again.
- The cache is never committed.

## Reading the numbers

!!! warning "Keep these in mind"
    - Context7's index changes over time: every number carries the run's date, and no two dates
      are compared.
    - Context7 indexes from its own sources and with its own chunking, which may not be the
      commits the corpus pins. Text that differs from the pinned commit's does not match its
      sections, so the `unmatched` share is worth reading next to recall.
    - The latencies include a call over the internet; ExactDocs' are its search alone, in-process.

## The Context7 report

`context7.json` (`schema_version` 1, in `reports/evals/` or `--out`). `context7.md` is the summary.

??? info "Fields of `context7.json`"
    - `golden`, `cases`, `projects`, `corpus`, `date`;
    - `tool`: `name`, `api`, `api_version`, `endpoint`, `token_budget`, `client`;
    - `environment`, `scorer`, `statistics`;
    - `coverage`: per version, `project`, `version`, `requested_id`, `status`, `resolved_id`,
      `served`, `date`;
    - `baseline`: ExactDocs' BM25 at `default` on every case;
    - `recorded`;
    - per group with questions, in `groups`: `name`, `about`, `versions`, `result`,
      `context_tokens_interval`, `rows`, `baseline` (BM25 on the group's cases) and `versus` (the
      paired tests);
    - `errors`: questions whose request failed, scored as empty.

The command exits with 1 when a request failed or a version's coverage is unknown.

## When it runs

- By hand, or with the manual workflow *Retrieval eval (real providers)*
  (`.github/workflows/eval-providers.yml`, input `context7`, repository secret
  `CONTEXT7_API_KEY`). The report is the `context7-bench` artifact, and the raw responses the
  `context7-responses` artifact.
- Never in pull request CI, which runs the quick tests (`tests/evals/test_context7_bench.py`,
  `context7_bench.feature`) against a stand-in that answers in the API's documented shape
  (`tests/fixtures/context7_stand_in.py`).
- The agent benchmark's `context7` arm (#495) reaches Context7 through its official MCP server
  instead ([Setting up the arms](agent-bench.md#setting-up-the-arms)); the same terms apply, and
  `just bench-pages` refuses to publish an agent run that has that arm.

## Terms of service

!!! danger "No Context7 number is published"
    No Context7 number is published, on the benchmark pages or elsewhere, until Upstash has given
    permission in writing. The run and its cache stay internal until then.

Context7's use is governed by two documents, read on 2026-11-25:

| Document | What it says |
|---|---|
| Upstash's Terms of Service (`upstash.com/trust/terms`, April 2025) | forbid benchmark tests or analyses of the services without Upstash's express permission (section C.8) |
| the Context7 Addendum (`upstash.com/trust/context7addendum.pdf`, August 2025) | grants use for internal development, educational and evaluation purposes; forbids using Outputs to build competing documentation services, bulk extraction for redistribution, and getting around rate limits (section 4) |
