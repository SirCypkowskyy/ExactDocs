# Comparison with other tools

!!! abstract "TL;DR"
    - Grounded Docs 3.4.1 against ExactDocs' BM25 at `default`, on the whole golden set, indexed
      and asked on 27 November 2026 on the same machine as ExactDocs' recorded run, ExactDocs'
      search grouped by article (#575).
    - Full-text only: ExactDocs leads on every metric, recall@1 70.8% against 59.2%, recall@5
      91.4% against 83.5%, recall@10 93.6% against 85.4% (all significant).
    - With `bge-small-en-v1.5`: recall@1 71.9% against 70.8% (p 0.74), recall@5 87.3% against
      91.4% (p 0.073) and recall@10 90.6% against 93.6% (p 0.15), none significant. Against
      ExactDocs' hybrid search with the same model, recall@5 93.3% is significantly ahead.
    - Its results hold about twice the context: 7,352 to 7,964 estimated tokens per question,
      against 3,465.
    - At the same amount of context ExactDocs finds the answer more often: within 1,000 tokens,
      43.1% against 34.5% with whole results and 80.5% against 57.7% with the text cut (Grounded
      Docs with `bge-small-en-v1.5`); it leads at 2,000 and 4,000 too, all significant.

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

Grounded Docs 3.4.1 indexed the golden corpus and answered the golden set on 27 November 2026,
in both configurations, on a 2-vCPU Linux aarch64 runner VM like those of ExactDocs' recorded
run. ExactDocs' BM25 at `default` is asked and scored the same way, with its results grouped by
article (#575; [before and after grouping](#before-and-after-grouping-by-article)). A hit is a
result that answers any section the case lists, a part or one of its alternatives, as in
[Retrieval metrics](../method/metrics.md#retrieval-metrics):

- **Full-text search only**, against ExactDocs' BM25:

    | Metric | Grounded Docs | ExactDocs BM25 | Significant |
    |---|---|---|---|
    | recall@1 | 59.2% | 70.8% | yes |
    | recall@5 | 83.5% | 91.4% | yes |
    | recall@10 | 85.4% | 93.6% | yes |
    | nDCG@10 | 0.660 | 0.757 | yes |

    It returns 7.5 results per question rather than 10, because it merges the nearby matches of a
    page into one result. ExactDocs' ten chunks come in 5.6 article groups per question.

- **With `bge-small-en-v1.5`**, against ExactDocs' BM25:

    | Metric | Grounded Docs | ExactDocs BM25 | Significant |
    |---|---|---|---|
    | recall@1 | 71.9% | 70.8% | no (p 0.74) |
    | MRR | 0.795 | 0.796 | no (p 0.97) |
    | recall@5 | 87.3% | 91.4% | no (p 0.073) |
    | recall@10 | 90.6% | 93.6% | no (p 0.15) |

    nDCG@10 does not differ significantly either (0.742 against 0.757). On 25 November, on the
    index it built on 24 November on 4 shared x86_64 CPUs, it scored 85.4% recall@5 and 88.8% recall@10,
    both significantly below BM25; this index ranks a few cases higher, and the difference is no
    longer significant.

    Against ExactDocs' hybrid search with the same model (the recorded run, scored by chunk ID),
    recall@5 (93.3%) and nDCG@10 (0.791) are significantly higher; recall@1 (76.4%, p 0.15),
    recall@10 (93.6%, p 0.16) and MRR (0.837, p 0.078) are higher but not significantly.
- **Twice the context.** Its results hold 7,352 to 7,964 estimated tokens per question, against
  ExactDocs' 3,465, and 2,032 to 2,282 tokens up to the first hit, against 1,444. That bigger
  context also holds more of the cases' facts (92% to 93%, against 87%).
- **At the same amount of context, ExactDocs finds the answer more often**: how often a
  section that answers is within the first 1,000, 2,000 and 4,000 estimated tokens of what each
  tool returned ([Method](../method/metrics.md#retrieval-metrics)):

    | Within | ExactDocs BM25 | Grounded Docs, `bge-small-en-v1.5` | Grounded Docs, full-text |
    |---|---|---|---|
    | 1,000 tokens, whole results | 43.1% | 34.5% | 25.1% |
    | 2,000 tokens, whole results | 71.5% | 58.4% | 53.6% |
    | 4,000 tokens, whole results | 89.5% | 76.8% | 70.8% |
    | 1,000 tokens, text cut | 80.5% | 57.7% | 44.9% |
    | 2,000 tokens, text cut | 88.8% | 71.5% | 65.9% |
    | 4,000 tokens, text cut | 93.3% | 84.3% | 77.9% |

    - Reading whole results is the harder rule for a tool with long results; cutting the text at
      the budget (the result the budget cuts counts when its part within the budget answers)
      favours them. ExactDocs leads at every budget under both, and every difference is
      significant (McNemar, p 0.015 or under).
    - ExactDocs' hybrid search with the same model finds it in 42.3%, 74.2% and 90.6%, whole
      results, each significantly more often than Grounded Docs (p 0.019 or under).
    - A group of ExactDocs' results holds about 620 tokens (3,465 in 5.6 groups), a Grounded Docs
      result about 1,000. An answer in a group's second or third chunk ends further into the text
      than it did as a result of its own, so ExactDocs' lead with whole results is narrower than
      before it grouped ([below](#before-and-after-grouping-by-article)).
- **Changelogs are left out.** Its default exclusion patterns skip `changelog.md` and
  `changelog.mdx` (and hidden files).
    - So it did not index Pydantic v1's and Zod v4's changelogs, and four answerable Zod v4 cases
      list no section outside `changelog.mdx` (two more list it next to another page).
    - Without those four (263 answerable cases), recall@5 is 84.8% full-text and 88.6% with the
      embedding model, against ExactDocs' 91.3%.
    - The `version-change` questions, which lean on such pages, are where it trails most
      (recall@5 80.4% full-text and 82.1% with the embedding model, against 96.4%).
- **No result of another version** from either tool (wrong-version rate 0); about 80% of both
  tools' results are version-neutral, so this says little on its own.
- **Indexing** the whole corpus (1,716 articles, 6,263 chunks) took 122 seconds with full-text
  search only (a 30.0 MB database) and 91 minutes with the embedding model on 2 vCPUs (80.8 MB),
  almost all of it embedding 2.5 million tokens (27 minutes on 4 shared CPUs on 24 November).

### Before and after grouping by article

ExactDocs' search returned one chunk per result until #575; it now groups them by article
([Retrieval results](../retrieval/grouping.md)). The grid ran it both ways on the same
code and machine on 25 November, scored by chunk ID, and Grounded Docs with `bge-small-en-v1.5`
was tested against each on the same cases. This table is from the Grounded Docs run of
25 November, on the golden set before #594 (`sha256:a00997851150e3b0`); it was not computed
again on the run above:

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
