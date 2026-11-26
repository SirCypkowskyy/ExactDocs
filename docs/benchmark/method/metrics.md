# Metrics and statistics

!!! abstract "TL;DR"
    - Retrieval: recall@k, MRR, nDCG@10, section recall, recall within a token budget, the
      wrong-version rate; a hit on any section a case lists counts.
    - Every number has a 95% percentile bootstrap interval over cases, every comparison a paired
      test (McNemar's mid-p or a sign-flip permutation).
    - Agent: accuracy graded by a blind LLM judge, answers true of another version only, tool calls
      and cost per question.

The definitions the result pages rely on, for each benchmark, and how their intervals and tests
are computed.

## Retrieval metrics

Answerable cases are the 267 cases that name sections; unanswerable cases are the other 54.

| Metric | Over | Definition |
|---|---|---|
| recall@k (k = 1, 5, 10) | answerable cases | share of cases with a section they list in the top k results: any part, any alternative |
| section recall@k (k = 5, 10) | answerable cases | per case, the share of its parts in the top k, averaged over cases[^section-recall] |
| MRR | answerable cases | mean of 1 / the rank of the first hit on a section the case lists;<br/>0 when there is none in the top 10 |
| nDCG@10 | answerable cases | binary relevance, divided by the ideal DCG[^ndcg] |
| wrong-version rate | every case | share of cases with any result of another version, read back by chunk ID;<br/>it must be 0, and a configuration with one is never recommended |
| unanswerable clean | unanswerable cases | share that returned nothing of another version |
| no answer | unanswerable cases | share that came back with no result at all, the only "no answer" signal `search_docs` has |
| answerable empty | answerable cases | share that came back with no result, a wrong "no answer" |
| p50 / p95 latency | every case | nearest-rank percentiles of the search alone,<br/>one question at a time, on the machine the run names |
| tokens / USD per question | every case | what the spend ledger grew by during each search[^spend];<br/>USD from the configured prices or `genai-prices` |
| index | per embedding model and chunking | seconds, tokens and USD of embedding the whole corpus once |
| context tokens / question | every case | estimated tokens (characters / 4) of all the text returned: every chunk's content for ExactDocs, every result's text for a tool scored from text |
| tokens to first hit | answerable cases with a hit in the top 10 | estimated tokens of the results up to and including the first that answers |
| recall within 1,000 / 2,000 / 4,000 tokens | answerable cases | the result that first answers the case ends within the first 1,000, 2,000 or 4,000 estimated tokens of the text returned, the results read whole and in order |
| the same, text cut | answerable cases, tools scored from text | the text returned, cut at the budget, answers the case: a result within the budget answers, or the result the budget cuts answers from its part within it |

**At the same amount of context** (#575). Tools return very different amounts of text per result:
an ExactDocs chunk at `default` holds about 350 estimated tokens, a Grounded Docs result about
1,000. A tool whose results are longer finds the answer in its first result more often for that
reason alone, so recall@1 and recall@5 do not compare tools at the same amount of context. Recall
within a token budget does: how often the answer is among the first 1,000, 2,000 or 4,000 tokens
a caller reads, the tokens the reports give as "context tokens / question". Neither way to read
a budget is neutral, so both are measured:

- *Whole results* counts a result only when all of it fits, the way a caller that takes results
  one at a time reads them. It favours a tool whose results are short.
- *Text cut* cuts the text at the budget and counts the result the budget cuts when its part
  within the budget answers (it holds the section, or lies in it, by the text scorer's rule). It
  favours a tool whose results are long, since the start of a long result can answer.
- Chunk-ID scoring cannot cut a chunk, so ExactDocs' own benchmark reports whole results only; a
  tool scored from its text gets both. Each comes with its interval and the paired test
  (McNemar, mid-p).

[^section-recall]: Each part is counted once, whichever of its alternatives answered it. Equal to
    recall@k for a case of one part, lower when a `cross-page` answer comes back only in part.
[^ndcg]: A hit at rank *i* scores 1 when it answers a part no earlier hit answered, else 0.
    DCG@10 = Σ *rel*<sub>i</sub> / log<sub>2</sub>(*i* + 1) over the top 10, divided by the ideal
    DCG, which puts every part first.
[^spend]: Embedding a query, a judgment, a HyDE answer, an agent run.

How a case lists its sections (#501):

- **Parts** are what a complete answer needs ("all of").
- Each part is followed by its **alternatives**: sections that answer that part as well, either
  being enough ("any of"). Examples are a reference page next to a guide, or the same fact in a
  release note.
- recall@k and MRR count the first hit on any section the case lists. A tool that returns another
  section that answers, or one part of a multi-page answer, is not scored a miss.
- Section recall and nDCG@10 count each part once, its alternatives counting as that part, so
  they show how much of a multi-page answer came back.

The [golden set](../golden-set.md) marks as alternatives the sections its review (#490) added
because they answer as well as the one listed.

## Intervals and significance

The golden set has a few hundred cases, so a difference of a few points between two
configurations can be noise. Every number a benchmark reports is a mean over cases (a rate is the
mean of a hit or a miss). Each number comes with a 95% interval, and each comparison with a
paired test (#489). The code is `packages/exactdocs/evals/retrieval_eval/stats.py`.

- **Intervals**: a percentile bootstrap over the cases.
    - 10,000 times, the cases are drawn again with replacement (as many as there are) and the
      metric recomputed. The interval runs from the 2.5th to the 97.5th percentile of those
      values.
    - The draws come from Python's `random.Random(489)` and depend only on the seed and the
      number of cases. Every configuration that answered the same cases is resampled with the
      same draws (a paired bootstrap), and a rerun gives the same intervals.
    - The report records the seed, the number of resamples, the confidence and the significance
      level (`statistics`).
    - A rate that is the same for every case (a wrong-version rate of 0) gets an interval of no
      width: the bootstrap cannot say more than the cases do.
- **Hit-or-miss outcomes** (recall@k, agent accuracy): McNemar's test on the cases where the two
  configurations disagree, in its mid-p version.
    - With *n* disagreements and *k* the smaller of "only A found it" and "only B found it", the
      p-value is 2 P(X < *k*) + P(X = *k*) for X ~ Binomial(*n*, ½).
    - The exact test counts P(X = *k*) twice and is conservative; the mid-p version keeps close
      to the nominal level (Fagerland, Lydersen and Laake, 2013).
- **Graded outcomes** (MRR, nDCG@10): a paired sign-flip permutation test.
    - Under no difference, each case's difference is as likely to have either sign.
    - 10,000 random sign patterns (same seed) give the p-value: the share of patterns whose mean
      difference is at least as far from 0 as the observed one (counting the observed one).
    - This is the randomization test Smucker, Allan and Carterette (2007) recommend for comparing
      retrieval systems.
- Each test also gives the difference with its paired bootstrap interval. A difference is
  **significant** when its p-value is under 5%.

What is tested against what:

- Each result of the retrieval benchmark is tested against its budget's default, on the
  answerable cases both answered. The table is under *Against the budget's default* on
  [Retrieval results](../retrieval/index.md).
- In the agent benchmark, each agent model's accuracy under a retrieval configuration is tested
  against its accuracy under the run's first configuration.

!!! warning "Small groups are wide"
    A question kind or a project holds about 50 cases, a fifth of the answerable ones, so its
    intervals are about twice as wide as the whole set's: at 80% recall, roughly ±11 points
    against ±5. Differences per kind or per project of a few points say little.

A result can be tested only when the report kept every case's outcome (`rows`). Every result of
the recorded retrieval run does (it was recorded again for #490).

## Scoring tools that return text

ExactDocs' results are scored by their chunk IDs. Tools that return text (Context7, Grounded
Docs, a grep or fixed-window baseline) are scored from the text alone, with the same metrics:

- Each pinned version's articles are cut at every heading with the importer's own parser and
  chunker.
- Texts are compared as sets of 5-word shingles after dropping markup, link targets and case.
- A result answers a section when it holds at least 80% of the section's own text, or when at
  least 80% of the result lies in the section with its subsections.
- By the versions whose sections it matches, a result is of the right version, of another
  version, version-neutral (the text is the same in both) or unmatched.

Besides the retrieval metrics, a tool scored from text is reported with:

- the share of version-neutral and unmatched results;
- the tokens of context it returned per question (characters / 4), and up to its first hit;
- the share of the case's facts its text holds.

The scorer was calibrated on ExactDocs' own BM25 results for the whole golden set, scored both
ways. At the `default` chunking it takes 99.8% of the hit and miss decisions (each expected
section's rank in the top 10, or a miss) as chunk-ID scoring does, against a criterion of 98%.
The threshold, the sweep that chose it and every disagreement are in
[Scoring text results](../../evals/text-scoring.md).
[Comparison with other tools](../comparison/index.md) scores other tools with it.

## Ingestion metrics

Coverage is the share of the golden set's expected sections that start a chunk (a section held
inside a bigger chunk is "held", not covered). Next to it:

- cuts inside fenced code, tables and lists;
- source characters that end up in no chunk;
- chunk sizes in estimated tokens (characters / 4) at p50, p95 and maximum;
- the share of chunks under 50 tokens;
- chunks holding more than one top-level heading;
- empty or wrong heading paths;
- headings the chunks miss or invent;
- MkDocs-specific losses.

The definitions are in [The ingestion benchmark](../../evals/ingestion.md).

## Agent metrics and the judge

The same agent model answers each case with each **documentation arm** (#495):

| Arm | The agent has |
|---|---|
| `none` | no tools: it answers from what it knows of that version or says it does not know |
| `exactdocs` | only the ExactDocs MCP tools |
| `context7` | only the official Context7 MCP server's tools, at a pinned release |
| `grounded-docs` | only Grounded Docs' read-only tools, over its index of the same pinned versions |

The arms get the same prompt, the same request limit and the same instructions apart from the
sentence about the documentation tool, and each agent is offered its arm's tools and nothing
else. No Context7 number is published until Upstash permits it
([Terms of service](../../evals/context7.md#terms-of-service)).

The judge is an LLM given the question, version, kind, reference answer, facts and the agent's
answer. It does not see the docs or the arm: every arm's product and tool names are removed from
the answer first. It grades:

| Grade | Meaning |
|---|---|
| `correct` | every fact, nothing contradicted |
| `partially_correct` | some facts, nothing contradicted |
| `wrong` | no fact, a contradiction or an invented API |
| `refused` | says the docs do not cover it, or that it does not know |

Accuracy is the share `correct`, plus `refused` on `unanswerable` cases, where refusing is the
right answer. The report also counts:

- answers true only of another version;
- refusals on answerable cases, and correct refusals on `unanswerable` ones;
- how often the agent read every part the case names in full (a section of each, or one of its
  alternatives; for `grounded-docs`, a whole page read with `read_page`; not measured for
  `context7`, whose text comes from its own index);
- whether it read another version;
- tool calls.

A run the provider failed on (rate limit, server error, after the retries) is an `error`, left
out of every rate and test. A run where the agent gave no answer (the request limit) is a miss.

Cost per question, each as mean with a 95% interval, p50 and p95:

- wall time, with the time lost to provider retries left out;
- input tokens;
- output tokens with the thinking;
- thinking tokens on their own: the provider's count where it reports one, otherwise estimated
  from the thinking text the model returns (the thinking's share of each response's characters
  times its output tokens), and *not returned* when there is neither;
- USD (*unpriced* when the model has no price, never 0).

Each arm is compared with `none` on the same cases, and `context7` and `grounded-docs` with
`exactdocs` too: accuracy by McNemar's test (mid-p), wall time and tokens by a paired sign-flip
permutation test, with the ratio of the means.

!!! warning "Judge agreement with hand labels: not measured yet"
    The judge is checked by labelling at least 50 answers of a real-model run by hand and
    comparing (`just agent-bench sample`, then `just agent-bench agreement`; see
    [Judge agreement](../../evals/agent-bench-running.md#judge-agreement)). The first real-model run
    ([Agent results](../agent/index.md)) is not labelled yet, so its accuracies rest on an unchecked
    judge.
