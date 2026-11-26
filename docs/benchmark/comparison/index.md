# Comparison with other tools

!!! abstract "TL;DR"
    - Grounded Docs 3.4.1 against ExactDocs' BM25 at `default`, on the whole golden set, indexed
      on 24 November 2026 and asked again on 25 November, next to ExactDocs' search grouped by
      article (#575).
    - Full-text only: ExactDocs leads on every metric, recall@1 70.4% against 58.4%, recall@5
      91.0% against 83.2%, recall@10 93.3% against 85.0% (all significant).
    - With `bge-small-en-v1.5`: recall@1 71.2% against 70.4%, no longer a significant lead (p 0.82;
      before grouping 12.7 points, p 0.0005); recall@5 85.4% against 91.0% and recall@10 88.8%
      against 93.3%, both significant for ExactDocs.
    - Its results hold about twice the context: 7,360 to 7,935 estimated tokens per question,
      against 3,464.
    - At the same amount of context ExactDocs finds the answer more often: within 1,000 tokens,
      42.7% against 34.1% with whole results and 80.2% against 58.1% with the text cut (Grounded
      Docs with `bge-small-en-v1.5`); it leads at 2,000 and 4,000 too, all significant. Grouping
      narrowed that lead with whole results (77.9% against 34.1% before).

ExactDocs next to other documentation tools, on the same [golden set](../golden-set.md): the same
questions about the same projects at the same pinned versions.

- Every tool's results are scored from their text with the
  [text scorer](../../evals/text-scoring.md), so each is measured with the retrieval
  benchmark's own metrics, intervals and paired tests ([Method](../method/index.md)).
- Every number records the tool's version, its settings and the date it was measured.
- The tools run as their documentation sets them up; nothing is tuned for the golden set.

## Which page do I need

| Page | What it holds |
|---|---|
| [How Grounded Docs was measured](grounded-docs.md) | the same documentation, questions and scorer; the recorded run |
| [Grounded Docs: every table](grounded-docs-results.md) | every result, the paired tests, per kind and project, indexing |
| [Every run](history.md) | every recorded run of another tool next to ExactDocs' baseline, sortable and filterable |

## Grounded Docs

[Grounded Docs](https://github.com/arabold/docs-mcp-server) (`@arabold/docs-mcp-server`, MIT) is
the closest open-source alternative: a self-hosted MCP server that indexes each library version
separately and searches it with full-text search, and with vector search when an embedding model
is configured. It ran on this machine, so it indexed exactly what ExactDocs imports. How the run
works, and how to repeat it: [Grounded Docs](../../evals/grounded-docs.md) in the evals reference.

Grounded Docs 3.4.1 indexed the golden corpus on 24 November 2026, in both configurations. Its
questions were asked again on 25 November on the indexes it built, next to ExactDocs' BM25 at
`default` asked and scored the same way, with its results grouped by article (#575;
[before and after grouping](#before-and-after-grouping-by-article)). A hit is a result that answers
any section the case lists, a part or one of its alternatives, as in
[Retrieval metrics](../method/metrics.md#retrieval-metrics):

- **Full-text search only**, against ExactDocs' BM25:

    | Metric | Grounded Docs | ExactDocs BM25 | Significant |
    |---|---|---|---|
    | recall@1 | 58.4% | 70.4% | yes |
    | recall@5 | 83.2% | 91.0% | yes |
    | recall@10 | 85.0% | 93.3% | yes |
    | nDCG@10 | 0.655 | 0.754 | yes |

    It returns 7.5 results per question rather than 10, because it merges the nearby matches of a
    page into one result. ExactDocs' ten chunks come in 5.6 article groups per question.

- **With `bge-small-en-v1.5`**, against ExactDocs' BM25:

    | Metric | Grounded Docs | ExactDocs BM25 | Significant |
    |---|---|---|---|
    | recall@1 | 71.2% | 70.4% | no (p 0.82) |
    | MRR | 0.781 | 0.792 | no |
    | recall@5 | 85.4% | 91.0% | yes |
    | recall@10 | 88.8% | 93.3% | yes |

    nDCG@10 does not differ significantly either.

    Against ExactDocs' hybrid search with the same model (the recorded run, scored by chunk ID),
    recall@1 is lower (71.2% against 76.0%, not significant, p 0.12), and recall@5 (92.5%),
    recall@10 (93.3%), MRR (0.832) and nDCG@10 (0.787) are significantly lower.
- **Twice the context.** Its results hold 7,360 to 7,935 estimated tokens per question, against
  ExactDocs' 3,464, and 2,004 to 2,332 tokens up to the first hit, against 1,448. That bigger
  context also holds more of the cases' facts (92% to 94%, against 87%).
- **At the same amount of context, ExactDocs finds the answer more often**: how often a
  section that answers is within the first 1,000, 2,000 and 4,000 estimated tokens of what each
  tool returned ([Method](../method/metrics.md#retrieval-metrics)):

    | Within | ExactDocs BM25 | Grounded Docs, `bge-small-en-v1.5` | Grounded Docs, full-text |
    |---|---|---|---|
    | 1,000 tokens, whole results | 42.7% | 34.1% | 24.7% |
    | 2,000 tokens, whole results | 71.2% | 58.4% | 53.2% |
    | 4,000 tokens, whole results | 89.1% | 75.3% | 69.7% |
    | 1,000 tokens, text cut | 80.2% | 58.1% | 44.2% |
    | 2,000 tokens, text cut | 88.4% | 72.7% | 65.5% |
    | 4,000 tokens, text cut | 92.9% | 82.0% | 76.8% |

    - Reading whole results is the harder rule for a tool with long results; cutting the text at
      the budget (the result the budget cuts counts when its part within the budget answers)
      favours them. ExactDocs leads at every budget under both, and every difference is
      significant (McNemar, p 0.014 or under).
    - ExactDocs' hybrid search with the same model finds it in 42.3%, 73.4% and 90.3%, whole
      results, each significantly more often than Grounded Docs (p 0.012 or under).
    - A group of ExactDocs' results now holds about 620 tokens (3,464 in 5.6 groups), a Grounded
      Docs result about 1,000. An answer in a group's second or third chunk ends further into
      the text than it did as a result of its own, so ExactDocs' lead with whole results is
      narrower than before it grouped ([below](#before-and-after-grouping-by-article)).
- **Changelogs are left out.** Its default exclusion patterns skip `changelog.md` and
  `changelog.mdx` (and hidden files).
    - So it did not index Pydantic v1's and Zod v4's changelogs, and four answerable Zod v4 cases
      list no section outside `changelog.mdx` (two more list it next to another page).
    - Without those four (263 answerable cases), recall@5 is 84.4% full-text and 86.7% with the
      embedding model, against ExactDocs' 90.9%.
    - The `version-change` questions, which lean on such pages, are where it trails most
      (recall@5 80.4% in both configurations, against 96.4%).
- **No result of another version** from either tool (wrong-version rate 0); about 80% of both
  tools' results are version-neutral, so this says little on its own.
- **Indexing** the whole corpus (1,716 articles, 6,263 chunks) took 95 seconds with full-text
  search only (a 29.9 MB database) and 27 minutes with the embedding model on 4 shared CPUs
  (80.6 MB), almost all of it embedding 2.5 million tokens.

### Before and after grouping by article

ExactDocs' search returned one chunk per result until #575; it now groups them by article
([Retrieval results](../retrieval/grouping.md)). The grid ran it both ways on the same
code and machine on 25 November, scored by chunk ID, and Grounded Docs with `bge-small-en-v1.5`
is tested against each on the same cases:

| Grounded Docs minus ExactDocs | BM25, one chunk per result | BM25, grouped | hybrid, one chunk per result | hybrid, grouped |
|---|---|---|---|---|
| recall@1 | **+12.7** (p 0.0005) | +0.8 (p 0.82) | **+7.1** (p 0.0495) | -4.9 (p 0.12) |
| recall@5 | -1.9 (p 0.44) | **-5.6** (p 0.014) | -4.1 (p 0.081) | **-7.1** (p 0.0022) |
| recall@10 | **-4.5** (p 0.03) | **-4.5** (p 0.03) | **-4.5** (p 0.041) | **-4.5** (p 0.041) |
| MRR | **+0.074** (p 0.005) | -0.011 (p 0.64) | +0.030 (p 0.26) | **-0.050** (p 0.032) |
| within 1,000 tokens | **-43.8** | **-8.6** (p 0.014) | **-46.4** | **-8.2** (p 0.012) |
| within 2,000 tokens | **-30.0** | **-12.7** | **-30.3** | **-15.0** |
| within 4,000 tokens | **-18.0** | **-13.9** | **-18.0** | **-15.0** |

Points of recall (MRR as a score), Grounded Docs' minus ExactDocs': a positive number is Grounded
Docs ahead. **Bold**: significant at 5% (McNemar's test, mid-p, or a permutation test for MRR); a
p-value not shown is under 0.001. Within a budget: whole results, read in order.

- Before grouping, Grounded Docs put a section that answers first significantly more often than
  either ExactDocs search. Grouped, neither difference is significant, and ExactDocs leads at
  recall@5 with both searches and at MRR with hybrid search.
- Grouping costs ExactDocs part of its lead within a token budget, which stays significant at
  every budget.
- With the text cut at the budget (BM25, scored from its text), ExactDocs found the answer within
  1,000, 2,000 and 4,000 tokens in 83.5%, 90.3% and 93.6% of the cases before grouping (the run
  of #586, before #571) and in 80.2%, 88.4% and 92.9% grouped, against Grounded Docs' 58.1%,
  72.7% and 82.0%.
