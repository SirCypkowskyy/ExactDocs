# Recommended defaults

!!! abstract "TL;DR"
    - **No models:** BM25 at chunking `default`, the shipped default. BM25 at `h2` scores 89.1%
      recall@5 against 87.6%, a lead that is not significant (p 0.42).
    - **Local models:** keep BM25 at `default`. Hybrid on `bge-small-en-v1.5` at `merge-400`
      reaches 91.0%, 3.4 points more, under the 5-point margin and not significant (mid-p 0.064).
    - **Hosted models:** not measured yet; the local recommendation applies.
    - From the retrieval run recorded on 24 November 2026.

The configuration ExactDocs recommends for each budget, from the recorded
[retrieval run](retrieval.md) on the [golden set](golden-set.md).

!!! note "When a dearer budget gets its own default"
    Only when it beats the cheaper one by at least 5 points of recall@5 **and** the difference is
    significant on the same cases (McNemar's test, p under 5%;
    [How a default is chosen](method.md#how-a-default-is-chosen)).

<!-- bench:defaults -->
| budget | configuration | chunking | USD / 1000 questions | why |
|---|---|---|---|---|
| none | `bm25` | `h2` | $0.0000 | best none configuration: `bm25` at `h2`: recall@5 89.1%, nDCG@10 0.724, MRR 0.737, wrong-version rate 0, p95 30 ms, $0.0000 per 1000 questions |
| local | `bm25` | `h2` | $0.0000 | best local configuration: `hybrid:bge-small-en-v1.5` at `merge-400`: recall@5 91.0%, nDCG@10 0.758, MRR 0.764, wrong-version rate 0, p95 78 ms, $0.0000 per 1000 questions; +1.9 points of recall@5 over `bm25`, under the 5-point margin (McNemar mid-p 0.327): the cheaper `bm25` at `h2` stays the default |
| hosted | not measured yet: needs a real-providers run | - | - | - |
<!-- /bench -->

## No models

Use **BM25 at chunking `default`**, the shipped default.

BM25 at `h2` comes first in the table above, but its lead does not change the default:

- BM25 at `h2` (only `#` and `##` start a chunk) reaches 89.1% recall@5 against 87.6% at
  `default`. That is a lead of 4 questions out of 267, and it is not significant on any metric:
  recall@5 p 0.42, recall@1 p 0.24, MRR p 0.13, nDCG@10 p 0.43
  ([Retrieval results](retrieval.md#against-the-budgets-default)).
- `h2` also returns about twice the text per question: 7,065 estimated tokens in ten results
  against 3,464.
- Between chunkings of one budget the benchmark names the best outright, so the table says `h2`.
  Changing the shipped default needs a significant gain, and this is not one.
- `merge-400` ties `default` (87.6%).

What `default` is, and how it compares with `h6`:

- Library settings `split_level` 3 and `max_chars` 4,000: headings `#` to `###` start a chunk,
  and a chunk over 4,000 characters is cut again at deeper headings.
- It reaches 87.6% recall@5 on the golden set against 85.8% for BM25 at `h6` (every heading
  starts a chunk), and it answers faster (p95 52 ms against 75 ms).
- The recall@5 gain is not significant on its own (p 0.11). MRR (+0.022) and nDCG@10 (+0.023)
  are significantly better than at `h6` (p 0.029 and 0.002).
- That changed the shipped default
  ([#381](https://github.com/SirCypkowskyy/ExactDocs/issues/381)), on the numbers of the
  time.[^381-numbers] **A library added without chunking settings gets this chunking.**

!!! tip "Libraries that already exist keep their chunking"
    A library stores its chunking, so the change re-chunks none of the libraries that exist.
    Those added with ExactDocs 0.4 or earlier keep `h6` (`split_level` 6, no bound). To move one,
    set its chunking to `split_level` 3 and `max_chars` 4,000 in the library's settings; its
    versions are re-chunked from the stored text.

[^381-numbers]: Those numbers counted only a case's first section and undercounted `h2` and
    `merge-400`.

## Local models

Keep **BM25 at `default`**.

- **Hybrid search on `BAAI/bge-small-en-v1.5` at `merge-400`**, the best local configuration,
  reaches 91.0% recall@5.
    - That is 3.4 points more than BM25 at `default` (1.9 more than at `h2`, the no-model pick
      above): under the 5-point margin, and not significant on the same cases (McNemar mid-p 0.064
      against `default`, 0.33 against `h2`).
    - It needs the corpus embedded first (23 minutes for the whole golden corpus at `merge-400`
      on a 4-CPU runner) and has a p95 of 78 ms there.
- **Hybrid at `default`** scores about the same (90.3%), so the default chunking does not hurt an
  instance that turns hybrid on. There it ranks the answer higher (recall@1, MRR and nDCG@10 are
  significantly better than BM25's) without finding significantly more of them in the top 5.
- **The cross-encoder on BM25 at `default`** reaches 89.5% (p 0.36) at about 2.5 s per question.

## Hosted models

!!! warning "Not measured yet"
    No hosted embedding model, LLM judge, HyDE or agentic configuration has run on the golden set.
    A run of the manual *Retrieval eval (real providers)* workflow (`eval-providers.yml`) with the
    `benchmark` input ticked produces the numbers.

Until then, the local recommendation applies.[^agent-results]

[^agent-results]: The first [agent results](agent.md), open-weight agents on Ollama Cloud with
    ExactDocs on BM25, measure the agent, not a hosted retrieval model.

## Known weak spots

Each names the issue whose benchmark found it; none has an issue of its own yet.

- **No "no answer" signal.** `search_docs` returned results for all 54 unanswerable cases in
  every configuration (0% empty), so an agent cannot tell from the results that a version's docs
  do not cover its question. Scores are comparable only within one search and no mode applies a
  relevance threshold. Found by the retrieval benchmark (#347).
- **Multi-page answers.** On `cross-page` questions one page of the answer usually comes back and
  the others often do not (section recall@5 33 to 34 points below recall@5). Found by #347.
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
