# Rank 1 at no more context (#575)

!!! abstract "TL;DR"
    - The grid tried, for BM25 and hybrid on `bge-small-en-v1.5`, the heading path in the text, a hit
      widened to its section, and the hits grouped by article.
    - Grouping the hits alone by article (`+article-hits`) lifts recall@1 by 12.0 points with BM25 and
      12.4 with hybrid search, from the same ten chunks; ExactDocs ships it since #575.
    - The answer then sits further into what is returned: within 1,000 tokens BM25 finds it in 43.5%
      of the cases, 78.3% without grouping, still more often than Grounded Docs.
    - The heading path in the text does nothing measurable; a parent section costs four times the
      context.

Grounded Docs put a section that answers first more often than ExactDocs' search did before #575
(recall@1 71.5% with `bge-small-en-v1.5` against 58.8%, [Comparison](../comparison/index.md)), with
results about three times as long. The
[retrieval grid](../../evals/retrieval-grid.md) measured the variants that could close that gap,
for BM25 and for hybrid search on `bge-small-en-v1.5`, each scored from its text and tested
against its control (the grid's own search at `default`, which scores as the shipped BM25 does)
and against the shipped default, BM25 at `default`:

- **The heading path in the text**, in front of the indexed text (`+context-indexed`) or of the
  embedded text (`+context-embedded`; ExactDocs' own vector index already embeds the title and the
  heading path).
- **A hit widened to its section**: its parent section with the subsections (`+parent`).
- **The hits grouped by article**, as Grounded Docs groups them: one result per article, ranked by
  its best hit, holding the article's hits in article order, with the chunk on either side of each
  (`+article`) or the hits alone (`+article-hits`, the same ten chunks as the control).

`packages/exactdocs/evals/results/retrieval-grid-rank1.json`, run on 25 November 2026 on 4 shared
CPUs (Linux x86_64) with `just retrieval-grid --offline --cells ...` (the cells are in
`evals/golden/matrix.yaml`, each naming its control). The app cell `hybrid:bge-small-en-v1.5` is
ExactDocs' own hybrid search at `default`, run again on that machine for its context. Every cell
here returns one chunk per result except the grouping variants, and the run predates #571.

**What it shows:**

- **Grouping the hits by article wins at rank 1, with the same context.** `+article-hits` returns
  the same ten chunks as its control, one result per article:

    | | BM25 | `+article-hits` | hybrid, bge-small | `+article-hits` | Grounded Docs, bge-small |
    |---|---|---|---|---|---|
    | recall@1 | 58.8% | **70.8%** | 65.9% | **78.3%** | 71.5% |
    | recall@5 | 87.6% | **91.0%** | 90.6% | **93.3%** | 85.8% |
    | recall@10 | 93.3% | 93.3% | 94.0% | 94.0% | 89.1% |
    | context tokens / question | 3,437 | 3,440 | 3,121 | 3,119 | 7,360 |

    - Against its control, recall@1 gains 12.0 points with BM25 and 12.4 with hybrid search, and
      recall@5 3.4 and 2.6 points, all significant (p 0.008 or under); recall@10 does not move,
      since the ten chunks are the same.
    - The same holds on top of the embedded heading path, the form of hybrid search ExactDocs ships
      (`+context-embedded+article-hits`: recall@1 75.7%, +12.4 points; recall@5 94.0%, +3.0).
- **But the answer then sits further into what is returned.** A result now holds several chunks,
  so recall within a token budget falls against the control: BM25 `+article-hits` finds the
  answer within 1,000 tokens in 43.5% of the cases (78.3% without grouping), within 2,000 in 71.5%
  (89.1%), whole results; with the text cut at the budget, 67.8% and 84.6%. It still finds it more
  often than Grounded Docs at every budget, under both rules (Grounded Docs with bge-small: 34.5%,
  58.8%, 75.7% whole; 58.4%, 73.0%, 82.4% cut).
- **With the neighbouring chunks (`+article`)** rank 1 gains a little more (BM25 72.3%, hybrid
  79.0%) and recall@5 too (92.9%, 94.4%), but the context doubles (6,881 and 6,239 tokens per
  question), and within 1,000 and 2,000 tokens it falls below Grounded Docs (BM25 23.2% and 52.8%,
  whole results).
- **Widening a hit to its parent section (`+parent`)** gains at rank 1 too (BM25 +4.5 points,
  hybrid +5.2), at four times the context (14,232 and 12,832 tokens per question), and loses at
  every budget.
- **The heading path in the text does nothing measurable.** In front of the indexed text:
  BM25 +0.8 points of recall@1 (p 0.38), hybrid +0.0; in front of the embedded text: hybrid
  -2.6 (p 0.13); both: -1.1 (p 0.56). ExactDocs' own index already weights the heading path for
  BM25 and embeds it for vectors.
- **Smaller chunks do not help the grouping**: `h6/bm25+article` reaches 70.4% at rank 1, below
  `default/bm25+article` (72.3%). The `h6` hybrid cells were not run (each embeds the corpus at
  `h6` again, about 40 minutes on this machine).

So grouping by article, the hits alone, is the variant that wins at rank 1 without losing recall@5
or adding context. ExactDocs' search groups its results so since #575
([Grouped by article](grouping.md)), and the benchmark reports recall within a token budget next
to recall@1, since grouping trades one for the other.

The grid's tables are on [Rank 1: every table](rank-one-tables.md).
