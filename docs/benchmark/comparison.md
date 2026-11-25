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

ExactDocs next to other documentation tools, on the same [golden set](golden-set.md): the same
questions about the same projects at the same pinned versions.

- Every tool's results are scored from their text with the
  [text scorer](../evals/text-scoring.md), so each is measured with the retrieval
  benchmark's own metrics, intervals and paired tests ([Method](method.md)).
- Every number records the tool's version, its settings and the date it was measured.
- The tools run as their documentation sets them up; nothing is tuned for the golden set.

## Grounded Docs

[Grounded Docs](https://github.com/arabold/docs-mcp-server) (`@arabold/docs-mcp-server`, MIT) is
the closest open-source alternative: a self-hosted MCP server that indexes each library version
separately and searches it with full-text search, and with vector search when an embedding model
is configured. It ran on this machine, so it indexed exactly what ExactDocs imports. How the run
works, and how to repeat it: [Grounded Docs](../evals/grounded-docs.md) in the evals reference.

Grounded Docs 3.4.1 indexed the golden corpus on 24 November 2026, in both configurations. Its
questions were asked again on 25 November on the indexes it built, next to ExactDocs' BM25 at
`default` asked and scored the same way, with its results grouped by article (#575;
[before and after grouping](#before-and-after-grouping-by-article)). A hit is a result that answers
any section the case lists, a part or one of its alternatives, as in
[Retrieval metrics](method.md#retrieval-metrics):

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
  tool returned ([Method](method.md#retrieval-metrics)):

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
([Retrieval results](retrieval.md#grouped-by-article-575)). The grid ran it both ways on the same
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

### How it was measured

- **Same documentation.** Every pinned version of every project was indexed from the files the
  ExactDocs importer takes at the pinned commit, byte for byte, as a local folder (`file://`), as
  the project's library at the version's name.
- **Same questions, same cut-off.** Each golden question went through Grounded Docs' `search_docs`
  MCP tool with the case's library and version and 10 results, the cut-off ExactDocs is measured
  at.
- **Same scorer.** Grounded Docs' results and ExactDocs' BM25 at `default`, asked in the same run,
  were both scored from their text, with the rules chunk-ID scoring uses: recall@k and MRR count
  the first hit on any section a case lists, section recall and nDCG@10 count each part once.
  ExactDocs' results are scored as its `search_docs` returns them, grouped by article: each group
  is one result, holding its chunks' text (#575). The paired tests compare the two case by case.
  ExactDocs' recorded `bm25` and
  `hybrid:bge-small-en-v1.5` (scored by chunk ID, which agrees with the text scorer on 99.8% of
  decisions at `default`) are listed for reference.
- **Its documented defaults.** Scraping, its default exclusion patterns, splitting, search and
  result assembly were left as they ship. Three settings were set:
    - telemetry off;
    - the corpus folder as the one folder it may read;
    - the embedding request timeout raised from 30 to 300 seconds, because the local CPU endpoint
      answers one request at a time and Grounded Docs sends several at once (it waits longer; it
      indexes and ranks the same).

    The crawl's depth limit was raised for the versions whose folders are deeper than its default
    of 3, so that every article was offered.
- **Same embedding model.** The vector configuration used `BAAI/bge-small-en-v1.5`, the model of
  ExactDocs' best local configuration, served from the same ONNX file through a local
  OpenAI-compatible endpoint, the way Grounded Docs reaches any local model. Grounded Docs stores
  this model's 384-dimension vectors padded with zeros to 512 (its table of known models says
  512), which changes no distance between two vectors.

!!! warning "What to keep in mind"

    - **Bigger results.** Each Grounded Docs result is the matching chunks with the context it
      assembles around them (parent sections, neighbouring and child sections), so its ten
      results hold more text than ExactDocs' ten chunks. A result that holds a section's text
      answers it, so compare recall with the context tokens per question and the tokens up to
      the first hit.
    - **Version-neutral text.** Most of a pinned version's text is the same in its other
      versions, so most results of both tools cannot be told apart by their text, and the
      wrong-version rate scored from text is a lower bound. Grounded Docs searches only the
      version it is asked for.
    - **Latency is not compared.** Grounded Docs answered through MCP over HTTP; ExactDocs' BM25
      latency is its search alone, in-process.

### The recorded run

<!-- bench:grounded-docs-run -->
- Grounded Docs 3.4.1 (npm `@arabold/docs-mcp-server`, integrity `sha512-IZQKYKs3p939Tt7N...`), Node.js v22.23.5; questions through its `search_docs` MCP tool with the case's library and version, 10 results.
- Run 2026-11-25T15:50:09+00:00: golden set 321 cases, fingerprint `sha256:a00997851150e3b0`, projects starlette, pydantic, tanstack-query, zod, electron; ExactDocs commit `bdefaa90e0630622c5d4c87d1bb7cb6ab764ad87`, Python 3.14.6, Linux x86_64, 4 CPUs.
- `full-text`: no embedding model: full-text search only, what it does when no provider credentials are set. Environment: none.
- `bge-small-en-v1.5`: full-text and vector search, BAAI/bge-small-en-v1.5 served locally through an OpenAI-compatible endpoint (OPENAI_API_BASE). Environment: `DOCS_MCP_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`, `OPENAI_API_BASE=<endpoint>/v1`, `OPENAI_API_KEY=local`.
  Embedding model BAAI/bge-small-en-v1.5 (revision `aa8f8b060edb`, 384 dimensions, stored at 512), served by retrieval_eval.openai_embeddings (fastembed, the ONNX file `exactdocs models pull` fetched): indexing 6,263 texts, 2,466,665 tokens, 1,599 s of embedding (0 requests abandoned by the client); questions 321 texts, 11 s.
<!-- /bench -->

<!-- bench:grounded-docs -->
### Every result

| Tool and configuration | Scored by | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | version-neutral | context tokens / question | tokens to first hit |
|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | text | 70.4% (64.8-76.0) | 91.0% (87.3-94.4) | 93.3% (90.3-96.2) | 0.792 (0.751-0.833) | 0.754 (0.717-0.790) | 0.0% | 80.8% | 3,465 (3,320-3,615) | 1,448 |
| ExactDocs bm25 @ default | chunk ID | 70.4% (64.8-76.0) | 91.0% (87.3-94.4) | 93.3% (90.3-96.2) | 0.792 (0.751-0.833) | 0.754 (0.717-0.790) | 0.0% | - | 3,464 (3,320-3,614) | 1,448 |
| ExactDocs hybrid:bge-small-en-v1.5 @ default | chunk ID | 76.0% (70.8-81.3) | 92.5% (89.1-95.5) | 93.3% (90.3-96.2) | 0.832 (0.793-0.869) | 0.787 (0.750-0.821) | 0.0% | - | 3,206 (3,072-3,340) | 1,413 |
| Grounded Docs full-text | text | 58.4% (52.4-64.4) | 83.2% (78.6-87.6) | 85.0% (80.5-89.1) | 0.685 (0.638-0.734) | 0.655 (0.612-0.698) | 0.0% | 80.9% | 7,935 (7,640-8,250) | 2,332 |
| Grounded Docs bge-small-en-v1.5 | text | 71.2% (65.9-76.4) | 85.4% (81.3-89.5) | 88.8% (85.0-92.5) | 0.781 (0.738-0.823) | 0.727 (0.687-0.766) | 0.0% | 79.7% | 7,360 (7,081-7,657) | 2,004 |

### Paired tests against ExactDocs

| Grounded Docs | against | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| full-text | ExactDocs bm25 @ default (text) | -12.0 points (-18.0 to -6.0), p 0.000142, significant | -7.9 points (-12.4 to -3.4), p 0.000472, significant | -8.2 points (-12.4 to -4.1), p 0.000191, significant | -0.107 (-0.151 to -0.062), p 0.0001, significant | -0.099 (-0.137 to -0.060), p 0.0001, significant |
| full-text | ExactDocs bm25 @ default (chunk ID) | -12.0 points (-18.0 to -6.0), p 0.000142, significant | -7.9 points (-12.4 to -3.4), p 0.000472, significant | -8.2 points (-12.4 to -4.1), p 0.000191, significant | -0.107 (-0.151 to -0.062), p 0.0001, significant | -0.099 (-0.137 to -0.060), p 0.0001, significant |
| full-text | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -17.6 points (-24.3 to -10.9), p 3.88e-07, significant | -9.4 points (-13.9 to -4.9), p 6.88e-05, significant | -8.2 points (-12.7 to -3.8), p 0.000606, significant | -0.146 (-0.196 to -0.096), p 0.0001, significant | -0.132 (-0.175 to -0.088), p 0.0001, significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (text) | +0.8 points (-5.6 to +7.1), p 0.822, not significant | -5.6 points (-10.1 to -1.1), p 0.0138, significant | -4.5 points (-8.2 to -0.8), p 0.0295, significant | -0.011 (-0.058 to +0.036), p 0.644, not significant | -0.027 (-0.067 to +0.013), p 0.2, not significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (chunk ID) | +0.8 points (-5.6 to +7.1), p 0.822, not significant | -5.6 points (-10.1 to -1.1), p 0.0138, significant | -4.5 points (-8.2 to -0.8), p 0.0295, significant | -0.011 (-0.058 to +0.036), p 0.644, not significant | -0.027 (-0.067 to +0.013), p 0.2, not significant |
| bge-small-en-v1.5 | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -4.9 points (-10.9 to +1.1), p 0.12, not significant | -7.1 points (-11.6 to -2.6), p 0.00222, significant | -4.5 points (-8.6 to -0.4), p 0.041, significant | -0.050 (-0.096 to -0.005), p 0.032, significant | -0.060 (-0.101 to -0.019), p 0.0053, significant |

### Within a token budget

Recall within the first 1,000, 2,000 and 4,000 estimated tokens (characters / 4) of the text each tool returned. Whole results: the result that first answers the case ends within the budget. Text cut: the text is cut at the budget, and the result the budget cuts counts when its part within the budget answers (scored from text only).

| Tool and configuration | Scored by | context tokens / question | tokens to first hit | within 1,000, whole results | within 2,000, whole results | within 4,000, whole results | within 1,000, text cut | within 2,000, text cut | within 4,000, text cut |
|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | text | 3,465 (3,320-3,615) | 1,448 | 42.7% (36.7-48.7) | 71.2% (65.5-76.4) | 89.1% (85.4-92.9) | 80.2% (75.3-84.6) | 88.4% (84.3-92.1) | 92.9% (89.5-95.9) |
| ExactDocs bm25 @ default | chunk ID | 3,464 (3,320-3,614) | 1,448 | 42.7% (36.7-48.7) | 71.2% (65.5-76.4) | 89.1% (85.4-92.9) | - | - | - |
| ExactDocs hybrid:bge-small-en-v1.5 @ default | chunk ID | 3,206 (3,072-3,340) | 1,413 | 42.3% (36.3-48.3) | 73.4% (68.2-78.6) | 90.3% (86.5-93.6) | - | - | - |
| Grounded Docs full-text | text | 7,935 (7,640-8,250) | 2,332 | 24.7% (19.9-30.0) | 53.2% (47.2-59.2) | 69.7% (64.0-75.3) | 44.2% (38.2-50.2) | 65.5% (59.9-71.2) | 76.8% (71.5-81.7) |
| Grounded Docs bge-small-en-v1.5 | text | 7,360 (7,081-7,657) | 2,004 | 34.1% (28.5-39.7) | 58.4% (52.4-64.4) | 75.3% (70.0-80.5) | 58.1% (52.1-64.0) | 72.7% (67.4-77.9) | 82.0% (77.5-86.5) |

### Paired tests within a token budget

| Grounded Docs | against | within 1,000, whole results | within 2,000, whole results | within 4,000, whole results | within 1,000, text cut | within 2,000, text cut | within 4,000, text cut |
|---|---|---|---|---|---|---|---|
| full-text | ExactDocs bm25 @ default (text) | -18.0 points (-24.3 to -11.6), p 1.23e-07, significant | -18.0 points (-24.3 to -11.6), p 8.41e-08, significant | -19.5 points (-25.1 to -13.9), p 3.24e-11, significant | -36.0 points (-42.3 to -29.6), p 2.8e-23, significant | -22.9 points (-28.5 to -17.2), p 1.74e-13, significant | -16.1 points (-21.0 to -11.2), p 3.89e-10, significant |
| full-text | ExactDocs bm25 @ default (chunk ID) | -18.0 points (-24.3 to -11.6), p 1.23e-07, significant | -18.0 points (-24.3 to -11.6), p 8.41e-08, significant | -19.5 points (-25.1 to -13.9), p 3.24e-11, significant | - | - | - |
| full-text | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -17.6 points (-24.3 to -10.9), p 7.25e-07, significant | -20.2 points (-27.0 to -13.5), p 1.72e-08, significant | -20.6 points (-26.2 to -15.0), p 2.96e-11, significant | - | - | - |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (text) | -8.6 points (-15.4 to -1.9), p 0.0138, significant | -12.7 points (-19.1 to -6.4), p 0.000224, significant | -13.9 points (-19.1 to -8.6), p 7.56e-07, significant | -22.1 points (-28.8 to -15.0), p 3.79e-09, significant | -15.7 points (-21.3 to -10.1), p 1.68e-07, significant | -10.9 points (-15.4 to -6.4), p 2.83e-06, significant |
| bge-small-en-v1.5 | ExactDocs bm25 @ default (chunk ID) | -8.6 points (-15.4 to -1.9), p 0.0138, significant | -12.7 points (-19.1 to -6.4), p 0.000224, significant | -13.9 points (-19.1 to -8.6), p 7.56e-07, significant | - | - | - |
| bge-small-en-v1.5 | ExactDocs hybrid:bge-small-en-v1.5 @ default (chunk ID) | -8.2 points (-14.6 to -1.9), p 0.0117, significant | -15.0 points (-21.3 to -8.6), p 5.66e-06, significant | -15.0 points (-20.6 to -9.4), p 2.79e-07, significant | - | - | - |

### Every metric scored from the text

| tool | recall@1 | recall@5 | recall@10 | section recall@5 | MRR | nDCG@10 | wrong version | no answer | version-neutral | unmatched | results / q | context tokens / q | tokens to first hit | facts found |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | 70.4% | 91.0% | 93.3% | 80.6% | 0.792 | 0.754 | 0.0% | 0.0% | 80.8% | 0.0% | 5.6 | 3465 | 1448 | 87.0% |
| Grounded Docs full-text | 58.4% | 83.2% | 85.0% | 72.3% | 0.685 | 0.655 | 0.0% | 0.0% | 80.9% | 0.2% | 7.5 | 7935 | 2332 | 92.3% |
| Grounded Docs bge-small-en-v1.5 | 71.2% | 85.4% | 88.8% | 75.0% | 0.781 | 0.727 | 0.0% | 0.0% | 79.7% | 0.5% | 7.0 | 7360 | 2004 | 93.5% |

### recall@5 by question kind

| Kind | ExactDocs bm25 @ default | Grounded Docs full-text | Grounded Docs bge-small-en-v1.5 |
|---|---|---|---|
| `conceptual` | 88.7% | 83.0% | 86.8% |
| `cross-page` | 91.7% | 87.5% | 95.8% |
| `how-to` | 87.9% | 82.8% | 82.8% |
| `identifier-lookup` | 90.4% | 82.7% | 82.7% |
| `unanswerable` | - | - | - |
| `version-change` | 96.4% | 80.4% | 80.4% |

### recall@5 and context by project

| Project | ExactDocs bm25 @ default | Grounded Docs full-text | Grounded Docs bge-small-en-v1.5 |
|---|---|---|---|
| starlette | 96.3%, 3,278 tokens | 96.3%, 5,363 tokens | 94.4%, 4,757 tokens |
| pydantic | 89.1%, 4,119 tokens | 70.9%, 8,523 tokens | 81.8%, 8,119 tokens |
| tanstack-query | 82.7%, 3,668 tokens | 86.5%, 7,952 tokens | 88.5%, 7,123 tokens |
| zod | 98.1%, 3,386 tokens | 86.8%, 7,360 tokens | 83.0%, 7,082 tokens |
| electron | 88.7%, 2,863 tokens | 75.5%, 10,413 tokens | 79.2%, 9,651 tokens |

### Indexing

| Configuration | Indexing time | Index size | Articles offered | Pages indexed | Chunks | Chunks with a vector |
|---|---|---|---|---|---|---|
| full-text | 95 s | 29.9 MB | 1,716 | 1,712 | 6,263 | 0 |
| bge-small-en-v1.5 | 1,644 s | 80.6 MB | 1,716 | 1,712 | 6,263 | 6,263 |

| Project | Version | Articles offered | Pages indexed | Chunks | Depth / pages passed | Seconds, full-text | Seconds, bge-small-en-v1.5 |
|---|---|---|---|---|---|---|---|
| starlette | 0.27.0 | 23 | 23 | 118 | 3 / 1000 | 3.5 | 38.2 |
| starlette | 0.52.1 | 25 | 25 | 154 | 3 / 1000 | 3.6 | 52.9 |
| starlette | 1.10.0 | 25 | 25 | 174 | 3 / 1000 | 4.3 | 63.6 |
| pydantic | v1.10.22 | 25 | 23 | 126 | 3 / 1000 | 4.7 | 40.4 |
| pydantic | v2.5.3 | 67 | 67 | 418 | 3 / 1000 | 6.0 | 126.6 |
| pydantic | v2.14.3 | 91 | 91 | 545 | 3 / 1000 | 6.0 | 162.4 |
| tanstack-query | v4.36.1 | 140 | 140 | 332 | 4 / 1000 | 5.5 | 75.2 |
| tanstack-query | v5.0.0 | 147 | 147 | 385 | 4 / 1000 | 6.1 | 91.5 |
| tanstack-query | v5.90.3 | 327 | 327 | 711 | 6 / 1000 | 10.2 | 143.2 |
| zod | v3.23.8 | 1 | 1 | 46 | 3 / 1000 | 3.1 | 17.1 |
| zod | v4.0.17 | 17 | 16 | 122 | 5 / 1000 | 3.9 | 36.7 |
| zod | v4.6.7 | 24 | 23 | 218 | 5 / 1000 | 3.9 | 65.2 |
| electron | v30.0.0 | 239 | 239 | 794 | 4 / 1000 | 11.6 | 192.0 |
| electron | v38.0.0 | 264 | 264 | 986 | 4 / 1000 | 11.2 | 253.8 |
| electron | v45.3.2 | 301 | 301 | 1,134 | 4 / 1000 | 11.7 | 285.0 |

Articles not indexed:

- pydantic v1.10.22: `docs/.benchmarks_table.md`, `docs/changelog.md`
- zod v4.0.17: `packages/docs/content/v4/changelog.mdx`
- zod v4.6.7: `packages/docs/content/v4/changelog.mdx`
- answerable cases that list no other article: 4 (zod v4.0.17: What should I use instead of .strict() and .passthrough() on objects?, zod v4.0.17: My .default("tuna") after a .transform() now has to be a number; how do I get the old pre-parse default?, zod v4.0.17: z.record(z.string()) used to work; why is it rejected now?, zod v4.6.7: An object with an a: z.unknown() field now fails when a is missing; did that change?)
<!-- /bench -->
