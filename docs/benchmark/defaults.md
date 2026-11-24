# Recommended defaults

The configuration ExactDocs recommends for each budget, from the recorded
[retrieval run](retrieval.md) on the [golden set](golden-set.md). A dearer budget gets its own
default only when it beats the cheaper one by at least 5 points of recall@5 and the difference
is significant on the same cases (McNemar's test, p under 5%;
[How a default is chosen](method.md#how-a-default-is-chosen)).

<!-- bench:defaults -->
| budget | configuration | chunking | USD / 1000 questions | why |
|---|---|---|---|---|
| none | `bm25` | `h2` | $0.0000 | best none configuration: `bm25` at `h2`: recall@5 89.1%, nDCG@10 0.724, MRR 0.737, wrong-version rate 0, p95 30 ms, $0.0000 per 1000 questions |
| local | `bm25` | `h2` | $0.0000 | best local configuration: `hybrid:bge-small-en-v1.5` at `merge-400`: recall@5 91.0%, nDCG@10 0.758, MRR 0.764, wrong-version rate 0, p95 78 ms, $0.0000 per 1000 questions; +1.9 points of recall@5 over `bm25`, under the 5-point margin (McNemar mid-p 0.327): the cheaper `bm25` at `h2` stays the default |
| hosted | not measured yet: needs a real-providers run | - | - | - |
<!-- /bench -->

## No models

Use **BM25 at chunking `default`**, the shipped default. Since #503 scores a chunk for every
section it holds, BM25 at `h2` (only `#` and `##` start a chunk) comes first in the table above:
82.8% recall@5 against 81.7% at `default`, a lead of 3 questions out of 267 that is not
significant on any metric (recall@5 p 0.58, recall@1 p 0.18, MRR p 0.11, nDCG@10 p 0.48;
[Retrieval results](retrieval.md#against-the-budgets-default)). `h2` also returns about twice
the text per question (7,065 estimated tokens in ten results against 3,464). Between chunkings
of one budget the benchmark names the best outright, so the table says `h2`; a change of the
shipped default needs a significant gain, and this is not one. `merge-400` ties `default`
(81.7%).

`default` is library settings `split_level` 3 and `max_chars` 4,000 (headings `#` to `###` start a chunk; a chunk over 4,000 characters is cut again at deeper
headings). It reaches 81.7% recall@5 on the golden set against 79.8% for BM25 at `h6`, where every
heading starts a chunk, and it answers faster (p95 57 ms against 91 ms).

The gain is 1.9 points, 5 more questions out of 267, and on its own it is not significant
(McNemar mid-p 0.07, 95% interval of the difference 0.0 to 3.8 points). The other measures point
the same way and are significant: at `default`, recall@10 (+2.2 points), MRR (+0.025) and nDCG@10
(+0.023) are better than at `h6` (p 0.016, 0.017 and 0.003). In the run #381 compared, `h2` and
`merge-400` also scored below `default`, but under the rule #503 fixed, which undercounted them.
That changed the shipped default
([#381](https://github.com/SirCypkowskyy/ExactDocs/issues/381)): **a library added without
chunking settings gets this chunking.** A library stores its chunking, so the change re-chunks
none of the libraries that exist. Those added with ExactDocs 0.4 or earlier keep `h6`
(`split_level` 6, no bound); to move one, set its chunking to `split_level` 3 and `max_chars`
4,000 in the library's settings, and its versions are re-chunked from the stored text.

## Local models

Keep **BM25 at `default`**. The best local configuration, hybrid search on
`BAAI/bge-small-en-v1.5` at `h6`, reaches 84.6% recall@5: 3.0 points more than BM25 at `default`
(1.9 more than at `h2`, the no-model pick above), under the 5-point margin, and not significant
on the same cases (McNemar mid-p 0.11 against `default`, 0.41 against `h2`). It also needs the corpus
embedded first (30 minutes for the whole golden corpus at `h6` on a 4-CPU runner) and a p95 of
109 ms there. Hybrid at `default` scores about the same (84.3%), so the default chunking does not
hurt an instance that turns hybrid on; there it ranks the answer higher (MRR and nDCG@10 are
significantly better than BM25's) without finding more of them in the top 5. The cross-encoder on
BM25 at `default` also reaches 84.6% (p 0.18) at about 2.5 s per question.

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
- **Cases reviewed by an agent only.** The golden set was written and checked by agents (#345);
  an independent agent review of 90 cases found 25.6% of them wrong in some way and fixed them
  (#490, [Golden set](golden-set.md)), but no person has reviewed them. The intervals measure
  sampling noise only (which cases happen to be in the set), not mistakes in the cases.
- **Gaps in the matrix.** `hybrid:bge-base-en-v1.5` did not run, and every hosted configuration
  is unmeasured (#347).
