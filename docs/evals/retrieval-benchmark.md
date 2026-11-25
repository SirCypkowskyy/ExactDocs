# The retrieval benchmark

!!! abstract "TL;DR"
    - The retrieval benchmark (#347) runs every retrieval configuration ExactDocs offers on the
      golden set, at every chunking configuration of the ingestion benchmark.
    - It names the configuration to use by default for each budget: no models, local models only,
      hosted models ([Recommendation and statistics](statistics.md)).
    - It scores `search_docs` as an agent reads it: grouped by article since #575, each group one
      result.
    - In the recorded run BM25 reaches recall@5 92.5% at `h2` and 91.0% at `default`. Hybrid on
      bge-small at `default` reaches 92.5%, as much as BM25 at `h2`: under the 5-point margin and
      not significant (p 1), so BM25 stays the default
      ([The recorded run](retrieval-runs.md#the-recorded-run)).
    - A run exits with 1 on a result of another version, a read outside the version, or a failed
      question.

```bash
just retrieval-bench --offline --configs bm25          # the model-free part: about a minute per chunking
just retrieval-bench --offline                          # + every local model that was pulled (hours, below)
just retrieval-bench --configs 'bm25*,hybrid:bge-small*' --chunkings default,h2 --projects zod
just retrieval-bench --out packages/exactdocs/evals/results    # refresh the recorded run
just retrieval-bench --configs bm25 --chunkings default --check   # what the Eval workflow runs
```

## What a run does

1. For each chunking configuration it imports every pinned version once, into a model-free
   instance of its own (the [ingestion benchmark](ingestion.md)'s import).
2. Every configuration runs on that data directory, in a container built with only the model roles
   it calls.
3. The corpus is embedded the first time an embedding model is used (as the `embed` jobs would,
   timed and costed as `index`).
4. Every golden question is asked in its project's library (`golden_run`), one at a time.

Hits are matched by the headings their chunk holds (`golden_run.held_match`, see
[Matching a hit across chunking depths](ingestion.md#matching-a-hit-across-chunking-depths)), so a
coarser or finer chunking is not penalised for cutting at another depth or merging sections.

**Grouped results** (#575). `search_docs` groups its results by article: an article's results
come together, best first, under its group's rank (`group`). The benchmark asks as the MCP tool
does, so it scores each group as one result (`dataset.results_of`): a case's rank is the rank of
the first group holding a hit that answers it, a group answers at most one part of a case (as a
text result does), and a group's tokens are those of all its chunks. `bench(group_by=...)` and
the grid's app cells with `group_by: chunk` measure the search before it grouped them, one chunk
per result.

It writes `retrieval.json` and `retrieval.md` to `reports/evals/` (or `--out`), prints the summary
and appends it to `$GITHUB_STEP_SUMMARY`. It exits with 1 when a configuration:

- returned a result of another version;
- read outside its version (agentic traces);
- or failed on a question.

## The matrix

| Configuration | Budget | Models |
|---|---|---|
| `bm25` | none | none |
| `bm25+ce` | local | the local cross-encoder (`Xenova/ms-marco-MiniLM-L-6-v2`, timeout 30 s) |
| `hybrid:<model>`<br/>`hybrid:<model>+ce` | local | a local embedding model[^local-models], and the cross-encoder |
| `hybrid:hosted`<br/>`hybrid:hosted+ce` | hosted | the embedding model `EXACTDOCS_AI__EMBEDDING__MODEL` names (and the local cross-encoder) |
| `<base>+judge` for each base above | hosted | the LLM judge, `EXACTDOCS_AI__JUDGE__MODEL` (else the `llm` role) |
| `hyde:hosted` | hosted | the hosted embedding model and `EXACTDOCS_AI__LLM__MODEL` |
| `agentic:hosted` | hosted | `EXACTDOCS_AI__LLM__MODEL` |

[^local-models]: By default `BAAI/bge-small-en-v1.5`, `snowflake/snowflake-arctic-embed-s` and
    `BAAI/bge-base-en-v1.5`; `--local-embeddings` changes the list.

### Selecting configurations

- Each runs at every chunking configuration (`default`, `h6`, `h2`, `merge-400`; `--chunkings`).
- `--configs` takes names or shell patterns (`'hybrid:*+ce'`).
- `<pattern>@<chunking>` runs a configuration at some chunkings only (`'*+ce@default'`).

A configuration that cannot run is listed with the reason:

| Status | Why |
|---|---|
| `unavailable` | a local model that was not pulled (with the `exactdocs models pull` command), or a hosted role that is not configured |
| `skipped` | a hosted configuration without `--allow-providers` |

!!! note "What cannot be swept yet"
    - The section ceiling of #141 (`max_section_chars`, 8,000 characters) applies to every
      configuration, but it is not a library setting, so it cannot be swept per configuration yet.
    - Nor can the ways to embed a chunk longer than the embedding model's window (bge-small reads
      about its first 1,800 characters), which have no setting either.

## Metrics

Each metric is reported per configuration and chunking, over all cases, per question kind
(`by_kind`) and per project (`by_project`).

### Ranking

| Metric | Over | Definition |
|---|---|---|
| recall@1, recall@5, recall@10 | answerable cases | a section the case lists (any part, any alternative) is in the top k |
| MRR | answerable cases | mean of 1 / the rank of the first hit on a section the case lists (0 past 10) |
| section recall@5, @10 | answerable cases | the share of a case's parts in the top k, averaged over the cases |
| nDCG@10 | answerable cases | binary relevance over the case's parts ([below](#ndcg10)) |

### Version and empty answers

| Metric | Over | Definition |
|---|---|---|
| wrong-version rate | every case | share of cases with a result of another version (read back by chunk ID, as in the suite); must be 0 |
| unanswerable clean | unanswerable cases | share that returned nothing of another version |
| no answer | unanswerable cases | share that signalled no answer: came back with no result |
| answerable empty | answerable cases | share that came back with no result (a "no answer" that was wrong) |

### Cost

| Metric | Over | Definition |
|---|---|---|
| p50 / p95 latency | every case | nearest-rank percentiles of the search alone, one question at a time, on the machine named in the report |
| tokens / USD per question | every case | what the spend ledger grew by during each search (an embedding, a judgment, a HyDE answer, an agent run); USD from the configured prices or `genai-prices` |
| index | per embedding model and chunking | seconds, tokens and USD of embedding the whole corpus once |

### Within a token budget

| Metric | Over | Definition |
|---|---|---|
| context tokens / question | every case | estimated tokens (characters / 4, `CHARS_PER_TOKEN`) of the content of every chunk returned: what a caller holds once it has read the results |
| tokens to first hit | answerable cases with a hit in the top 10 | estimated tokens of the chunks up to and including the first that answers |
| recall within 1,000 / 2,000 / 4,000 tokens | answerable cases | the result that first answers the case ends within the first 1,000, 2,000 or 4,000 estimated tokens of the text returned, the results read whole and in order |

Tools return very different amounts of text per result (#575): an ExactDocs chunk at `default`
holds about 350 estimated tokens, a Grounded Docs result about 1,000, a section widened to its
parent more. A tool whose results are longer finds the answer in its first result more often for
that reason alone, so recall@k does not compare tools at the same amount of context. Recall within
a budget does.

- **Whole results.** The results are read in order, whole, and a case counts when the first result
  that answers it ends within the first *B* estimated tokens of what was returned: its tokens to
  the first hit are at most *B*. This favours a tool whose results are short.
- **Text cut at the budget.** A tool scored from its text
  ([Text scoring](text-scoring.md)) is also measured with its text cut at *B*: a case counts as
  well when the result the budget cuts answers it from its part within the budget, by the text
  scorer's own rule (the part holds the section, or lies in it). This is the literal "the answer
  is in the first *B* tokens", and it favours a tool whose results are long. Chunk-ID scoring
  cannot cut a chunk, so ExactDocs' own benchmark reports whole results only.
- The budgets are `TOKEN_BUDGETS`; the tokens are those of "context tokens / question". Each comes
  with its interval, and each result is tested against its budget's default by McNemar's test
  (mid-p), as recall@k is.
- A row recorded before #575 kept no sizes, and its result has no budget numbers.

### nDCG@10

A returned hit at rank *i* is relevant (*rel* = 1) when it answers a part of the case (one of its
sections or of their alternatives) that no earlier hit answered. So a part found twice, or through
two of its alternatives, counts once; otherwise *rel* = 0.

- DCG@10 = Σ<sub>i=1..10</sub> *rel*<sub>i</sub> / log<sub>2</sub>(*i* + 1).
- The ideal DCG puts every part first: IDCG@10 = Σ<sub>i=1..min(R, 10)</sub> 1 /
  log<sub>2</sub>(*i* + 1), with *R* the number of parts.
- nDCG@10 = DCG@10 / IDCG@10.

### Cases with several expected sections

This covers `cross-page` cases and any case listing more than one section (#501).

- **recall@k and MRR** count the first hit on **any** section the case lists: a part, or an
  alternative of one (`VersionAndRank`, `first_rank`).
    - A tool that returns the reference page where ExactDocs returns the guide, both of which
      answer, is not scored a miss.
    - A tool that returns the second page of a two-page answer has found an answer.
- **Section recall@k and nDCG@10** say how much of the answer came back. They count each **part**
  once, its alternatives counting as that part.
    - A case scores the share of its parts found in the top k (each found part counted once, by
      the hit matching rule above), and section recall is the mean over cases.
    - For a case of one part it equals recall@k.
- The per-kind and per-project tables show recall@5, section recall@5 and nDCG@10 side by side,
  so the `cross-page` row says how often the whole answer came back, not only a part of it.

!!! info "Before #501"
    recall@k and MRR counted the first listed section only, as the fixture suite did, and section
    recall and nDCG@10 counted every listed section as a part. The fixture's cases list one
    section each, so its numbers are the same under both rules.

### "No answer"

`search_docs` has no explicit no-answer signal. A result carries a `score` that is "only
comparable within one search", and no mode applies a relevance threshold. The only signal a caller
can read is an empty result list.

| Mode | When it returns nothing |
|---|---|
| BM25 | only when no term of the question is in the version |
| `hybrid` | never: it always returns the nearest chunks |
| cross-encoder, judge | they reorder and never drop |
| `agentic` | it answers with the chunks the agent picks |

- The benchmark counts an empty result as "signalled no answer".
- It also reports how often an answerable case came back empty, so a configuration that returns
  nothing more often is not rewarded for it.
- In the recorded run no configuration signalled no answer for any of the 54 unanswerable cases
  (0%), while all of them returned nothing of another version. A caller cannot tell an
  unanswerable question from an answerable one by the result list today.
