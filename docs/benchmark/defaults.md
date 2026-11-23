# Recommended defaults

The configuration ExactDocs recommends for each budget, from the recorded
[retrieval run](retrieval.md) on the [golden set](golden-set.md). A dearer budget gets its own
default only when it beats the cheaper one by at least 5 points of recall@5
([How a default is chosen](method.md#how-a-default-is-chosen)).

<!-- bench:defaults -->
| budget | configuration | chunking | USD / 1000 questions | why |
|---|---|---|---|---|
| none | `bm25` | `default` | $0.0000 | best none configuration: `bm25` at `default`: recall@5 81.7%, nDCG@10 0.705, MRR 0.651, wrong-version rate 0, p95 57 ms, $0.0000 per 1000 questions |
| local | `bm25` | `default` | $0.0000 | best local configuration: `hybrid:bge-small-en-v1.5` at `h6`: recall@5 84.6%, nDCG@10 0.738, MRR 0.675, wrong-version rate 0, p95 127 ms, $0.0000 per 1000 questions; +3.0 points of recall@5 over `bm25`, under the 5-point margin: the cheaper `bm25` at `default` stays the default |
| hosted | not measured yet: needs a real-providers run | - | - | - |
<!-- /bench -->

## No models

Use **BM25 at chunking `default`**: library settings `split_level` 3 and `max_chars` 4,000
(headings `#` to `###` start a chunk; a chunk over 4,000 characters is cut again at deeper
headings). It reaches 81.7% recall@5 on the golden set against 79.8% for BM25 at `h6`, where every
heading starts a chunk, and it answers faster (p95 57 ms against 91 ms).

The gain is 1.9 points, 5 more questions out of 267. It was enough to change the shipped default
([#381](https://github.com/SirCypkowskyy/ExactDocs/issues/381)): **a library added without
chunking settings gets this chunking.** A library stores its chunking, so the change re-chunks
none of the libraries that exist. Those added with ExactDocs 0.4 or earlier keep `h6`
(`split_level` 6, no bound); to move one, set its chunking to `split_level` 3 and `max_chars`
4,000 in the library's settings, and its versions are re-chunked from the stored text.

## Local models

Keep **BM25 at `default`**. The best local configuration, hybrid search on
`BAAI/bge-small-en-v1.5` at `h6`, reaches 84.6% recall@5: 3.0 points more, under the 5-point
margin. It also needs the corpus embedded first (17 minutes for the whole golden corpus on a
10-core laptop) and a p95 of 127 ms. Hybrid at `default` scores about the same (84.3%), so
the default chunking does not hurt an instance that turns hybrid on.

## Hosted models

**Not measured yet.** No hosted embedding model, LLM judge, HyDE or agentic configuration has
run on the golden set. A run of the manual *Retrieval eval (real providers)* workflow
(`eval-providers.yml`) with the `benchmark` input ticked produces the numbers, and the
[agent results](agent.md) need a run of *Agent benchmark (real providers)* (`agent-bench.yml`).
Until then, the local recommendation applies.

## Known weak spots

Each names the issue whose benchmark found it; none has an issue of its own yet.

- **No "no answer" signal.** `search_docs` returned results for all 54 unanswerable cases in
  every configuration (0% empty), so an agent cannot tell from the results that a version's docs
  do not cover its question. Scores are comparable only within one search and no mode applies a
  relevance threshold. Found by the retrieval benchmark (#347).
- **Multi-page answers.** On `cross-page` questions the second section often stays out of the top
  5 (section recall@5 up to 19 points below recall@5). Found by #347.
- **Importer problems in the corpus.** Zod v4's MDX pairs code fences wrongly and hides 60
  headings, Pydantic keeps `{#id}` attributes in heading paths, MkDocs admonitions and tabs are
  read as code blocks, and Pydantic v1's includes stay unexpanded. Found by the golden set (#345)
  and measured by the ingestion benchmark (#346).
- **Unreviewed cases.** The golden set was written and checked by agents, not people (#345), so
  differences of a point or two between configurations may be within its error.
- **Gaps in the matrix.** `hybrid:bge-base-en-v1.5` did not run, the cross-encoder ran only at
  `h6` and `h2` (not at today's `default`), and every hosted configuration is unmeasured (#347).
