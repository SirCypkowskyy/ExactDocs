# Comparison with other tools

!!! abstract "TL;DR"
    - **Retrieval** (321 golden questions, 27 November 2026): ExactDocs' BM25 against Grounded
      Docs 3.4.1. Full-text only, ExactDocs leads on every metric (recall@5 91.4% against 83.5%,
      significant). With `bge-small-en-v1.5`, Grounded Docs is level with BM25 (recall@5 87.3%,
      p 0.073), and ExactDocs' hybrid search with the same model is ahead (93.3%, significant).
    - **Agents** (60 questions, two models): ExactDocs and Grounded Docs both lift accuracy far
      above no docs (`kimi-k3`: 83.3% and 81.7% against 33.3%) and are level with each other;
      Grounded Docs needs fewer tool calls and less time.
    - **Coding tasks** (six tasks): Codex CLI and OpenCode, with and without ExactDocs. Every
      difference is within noise at this size.
    - **Not measured yet**: Context7 in any benchmark (#493, its terms forbid publishing),
      Grounded Docs in the coding tasks, Claude Code and Gemini CLI, and the plain baselines of
      #494.

ExactDocs next to other documentation tools and next to no documentation, on the same
[golden set](../golden-set.md): the same questions about the same projects at the same pinned
versions. Every table is generated from a recorded run by `just bench-pages`
([Refreshing these pages](../method/runs.md#refreshing-these-pages)), and pull request CI fails
when a page no longer matches its run.

- Every number comes with its 95% interval and, against another arm, a paired test
  ([Method](../method/index.md)).
- Every run records the tools' versions, their settings and the date it ran.
- The other tools run as their documentation sets them up; nothing is tuned for the golden set
  ([Fairness](fairness.md)).

## Which page do I need

| Page | What it holds |
|---|---|
| [Agents, per documentation arm](agents.md) | the agent benchmark's arms: no docs, ExactDocs, Grounded Docs |
| [Coding tasks](coding.md) | coding tasks per harness, model and arm, with hidden tests |
| [Fairness and reproducing](fairness.md) | what was and was not tuned, the golden set's error rate, the commands, where raw reports go |
| [How Grounded Docs was measured](grounded-docs.md) | the same documentation, questions and scorer; the recorded run |
| [Grounded Docs: every table](grounded-docs-results.md) | every result, the paired tests, per kind and project, indexing |
| [Every run](history.md) | every recorded run of another tool next to ExactDocs' baseline, sortable and filterable |

## What is measured

- **Retrieval**: ExactDocs and Grounded Docs (both configurations). Context7's run is built
  (#493) but no number of it is published
  ([Terms of service](../../evals/context7.md#terms-of-service)). The plain baselines of #494
  (keyword grep over the raw Markdown, a fixed-window RAG) are declared in the grid but not in
  its recorded run.
- **Agents** ([Agents](agents.md)): no docs, ExactDocs and Grounded Docs. The `context7` arm is
  built (#495) and has not run.
- **Coding tasks** ([Coding tasks](coding.md)): no docs and ExactDocs, without a harness and in
  Codex CLI and OpenCode. Grounded Docs and Context7 have not run there, and Claude Code and
  Gemini CLI have not run at all: they need paid API keys (#497).

## Retrieval: Grounded Docs

[Grounded Docs](https://github.com/arabold/docs-mcp-server) (`@arabold/docs-mcp-server`, MIT) is
the closest open-source alternative: a self-hosted MCP server that indexes each library version
separately and searches it with full-text search, and with vector search when an embedding model
is configured. It ran on this machine, so it indexed exactly what ExactDocs imports. How the run
works, and how to repeat it: [How Grounded Docs was measured](grounded-docs.md).

Grounded Docs 3.4.1 indexed the golden corpus and answered the golden set on 27 November 2026,
in both configurations, on a 2-vCPU Linux aarch64 runner VM like those of ExactDocs' recorded
run. ExactDocs' BM25 at `default` is asked and scored the same way, with its results grouped by
article (#575). A hit is a result that answers any section the case lists, a part or one of its
alternatives, as in [Retrieval metrics](../method/metrics.md#retrieval-metrics). In parentheses:
the 95% interval.

<!-- bench:comparison-retrieval -->
| Tool and configuration | Scored by | recall@1 | recall@5 | recall@10 | MRR | nDCG@10 | wrong version | version-neutral | context tokens / question | tokens to first hit |
|---|---|---|---|---|---|---|---|---|---|---|
| ExactDocs bm25 @ default | text | 70.8% (65.2-76.4) | 91.4% (88.0-94.4) | 93.6% (90.6-96.2) | 0.796 (0.755-0.836) | 0.757 (0.721-0.793) | 0.0% | 80.8% | 3,465 (3,320-3,615) | 1,444 |
| ExactDocs bm25 @ default | chunk ID | 70.8% (65.2-76.4) | 91.4% (88.0-94.4) | 93.6% (90.6-96.2) | 0.796 (0.755-0.836) | 0.757 (0.721-0.793) | 0.0% | - | 3,464 (3,320-3,614) | 1,444 |
| ExactDocs hybrid:bge-small-en-v1.5 @ default | chunk ID | 76.4% (71.2-81.3) | 93.3% (89.9-96.2) | 93.6% (90.6-96.2) | 0.837 (0.798-0.873) | 0.791 (0.755-0.825) | 0.0% | - | 3,212 (3,077-3,346) | 1,410 |
| Grounded Docs full-text | text | 59.2% (53.2-65.2) | 83.5% (79.0-88.0) | 85.4% (81.3-89.5) | 0.693 (0.646-0.741) | 0.660 (0.618-0.703) | 0.0% | 80.8% | 7,964 (7,672-8,280) | 2,282 |
| Grounded Docs bge-small-en-v1.5 | text | 71.9% (66.3-77.1) | 87.3% (83.2-91.0) | 90.6% (87.3-94.0) | 0.795 (0.754-0.836) | 0.742 (0.704-0.780) | 0.0% | 79.7% | 7,352 (7,076-7,649) | 2,032 |
<!-- /bench -->

The paired tests behind "significant" below, and the tables per kind, project and token budget,
are on [Grounded Docs: every table](grounded-docs-results.md).

- **Full-text search only**, against ExactDocs' BM25: Grounded Docs is significantly lower on
  every metric. It returns 7.5 results per question rather than 10, because it merges the nearby
  matches of a page into one result. ExactDocs' ten chunks come in 5.6 article groups per
  question.
- **With `bge-small-en-v1.5`**, against ExactDocs' BM25: no metric differs significantly
  (recall@1 p 0.74, recall@5 p 0.073, recall@10 p 0.15). On 25 November, on the index it built
  on 24 November on 4 shared x86_64 CPUs, it scored 85.4% recall@5 and 88.8% recall@10, both
  significantly below BM25 ([Every run](history.md)).
    - Against ExactDocs' hybrid search with the same model, recall@5 and nDCG@10 are
      significantly higher; recall@1 (p 0.15), recall@10 (p 0.16) and MRR (p 0.078) are higher
      but not significantly.
- **Where Grounded Docs does better**: with the embedding model its recall@1 (71.9%) is above
  ExactDocs' BM25 (70.8%), not significantly. Its bigger results also hold more of the cases'
  facts (92% to 93%, against 87%).
- **Twice the context.** Its results hold 7,352 to 7,964 estimated tokens per question, against
  ExactDocs' 3,465, and 2,032 to 2,282 tokens up to the first hit, against 1,444.
- **At the same amount of context, ExactDocs finds the answer more often**: within the first
  1,000, 2,000 and 4,000 estimated tokens of what each tool returned, with whole results or the
  text cut at the budget, ExactDocs leads at every budget, and every difference is significant
  (McNemar, p 0.015 or under;
  [Within a token budget](grounded-docs-results.md#within-a-token-budget)).
    - Reading whole results is the harder rule for a tool with long results; cutting the text at
      the budget favours them.
    - A group of ExactDocs' results holds about 620 tokens (3,465 in 5.6 groups), a Grounded Docs
      result about 1,000.
- **Changelogs are left out.** Its default exclusion patterns skip `changelog.md` and
  `changelog.mdx` (and hidden files).
    - So it did not index Pydantic v1's and Zod v4's changelogs, and four answerable Zod v4 cases
      list no section outside `changelog.mdx` (two more list it next to another page).
    - The `version-change` questions, which lean on such pages, are where it trails most
      ([recall@5 by question kind](grounded-docs-results.md#recall5-by-question-kind)).
- **No result of another version** from either tool (wrong-version rate 0); about 80% of both
  tools' results are version-neutral, so this says little on its own.
- **Indexing** the whole corpus took 122 seconds with full-text search only and 91 minutes with
  the embedding model on 2 vCPUs, almost all of it embedding 2.5 million tokens
  ([Indexing](grounded-docs-results.md#indexing)).

### Before and after grouping by article

ExactDocs' search returned one chunk per result until #575; it now groups them by article
([Retrieval results](../retrieval/grouping.md)). Grouping put a section that answers first more
often (recall@1, MRR) and cost ExactDocs part of its lead within a token budget, which stayed
significant at every budget. Grounded Docs' runs of 24 and 25 November, on the golden set before
#594 (`a0099785`), are on [Every run](history.md) next to ExactDocs' BM25 of each day.
