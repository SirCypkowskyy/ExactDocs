# Scoring text results

!!! abstract "TL;DR"
    - Other documentation tools return text, not chunk IDs. The text scorer (#491) decides from the
      text alone which golden sections a result holds, and scores it with the retrieval
      benchmark's own metrics.
    - It is deterministic and needs no model: 5-word shingles, and a match at 80% of a section's
      shingles.
    - Calibrated against chunk-ID scoring on BM25, it agrees on 99.8% of decisions at `default`,
      above the 98% criterion, and at least 99.5% at every chunking.
    - Most text is the same across pinned versions, so its wrong-version rate is a lower bound.

The retrieval benchmark scores ExactDocs by reading each result's chunk ID back. Other
documentation tools return text: Context7's context endpoint, Grounded Docs' search, a grep or a
fixed-window RAG baseline. The text scorer decides which sections of the golden corpus a result
holds, in every pinned version of the project.

| Part | Code |
|---|---|
| the matcher | `retrieval_eval/text_match.py` |
| the rows, metrics, calibration and report | `retrieval_eval/text_bench.py` |

The runs of other tools (#492, #493, #494) score with it: see [Grounded Docs](grounded-docs.md)
and [Context7](context7.md).

```bash
just text-bench --offline                                         # calibrate at `default`: about two minutes
just text-bench --offline --chunkings default,h6,h2,merge-400     # at every chunking
just text-bench --offline --chunkings default,h6,h2,merge-400 --out packages/exactdocs/evals/results   # refresh the recorded run
```

## Matching a text to sections

### Sections

- Each pinned version's articles (the files the importer takes, read at the pinned commit) are cut
  with the importer's own parser and chunker.
- Every heading starts a section, with no size bound (`SECTION_CHUNKING`, the golden set's `h6`).
  A section is one heading's own text, up to the next heading.
- `golden-validate` cuts the same headings, so these are the sections the cases name.
- A heading path that occurs twice in an article is one section with two texts.

### Normalized text

- HTML entities are decoded, and the text NFKC-normalized.
- Dropped: code fence info strings, ordered-list numbers, Markdown link targets, bare URLs, and
  HTML or JSX tags.
- The rest is case folded and split into words of letters and digits (`on_startup` is
  `on startup`).
- A text is compared as the set of its 5-word shingles (`SHINGLE_WORDS`). A text of fewer words is
  one shingle.

So a reflowed paragraph, another list marker, Markdown rendered as plain text or a link without its
URL still matches. A paraphrase does not.

### A result answers a section

A result answers a section when either holds, at 80% (`MATCH_THRESHOLD`):

| Case | Rule | Example |
|---|---|---|
| the section is inside the result | the result holds at least 80% of the shingles of the section's own text | a coarser result, such as a chunk of several sections |
| the result is a part of the section | at least 80% of the result's own shingles are in the section with its subsections | a finer result, such as a window of it or a part of a long section |

These are the text forms of the rule chunk-ID scoring matches hits with (`golden_run.held_match`,
see [Matching a hit across chunking depths](ingestion.md#matching-a-hit-across-chunking-depths)),
so both scorings count the same hits.

### Version

For a question about version V, a result is:

| Verdict | Its text matches |
|---|---|
| *right* | sections of V and of no other pinned version |
| *version-neutral* | sections of V and of another version (the text is the same in both, so it cannot say which it came from) |
| *wrong-version* | sections of another version and none of V |
| *unmatched* | no section at all (text from elsewhere, or too little of it) |

## Metrics of text results

A tool's answer to a question is the text of each of its results, best first (`TextAnswer`). Each
tool's harness splits the tool's response into its results, in the tool's order.

Each case becomes the retrieval benchmark's own `Row`, so the metrics are computed by the same code
(`metrics_of`) with [the same definitions](retrieval-benchmark.md#metrics):

- recall@1/5/10, MRR, section recall and nDCG@10 over the top 10;
- the wrong-version rate, unanswerable clean, no answer, answerable empty;
- latency, model tokens and USD when the harness measures them.

A hit is the first result in the top 10 that answers a section the case lists. Each part counts
once in section recall and nDCG@10, its alternatives with it, as in the benchmark. A case is
wrong-version when any of its results is.

Next to them:

| Metric | Over | Definition |
|---|---|---|
| version-neutral | every result returned | share whose text matches the version asked and another pinned version |
| unmatched | every result returned | share whose text matches no section of any pinned version |
| results / question | every case | results returned |
| context tokens / question, p95 | every case | estimated tokens of all the text returned (characters / 4, as `CHARS_PER_TOKEN`)[^context] |
| tokens to first hit | answerable cases with a hit in the top 10 | estimated tokens of the results up to and including the first that answers a section the case lists |
| recall within 1,000 / 2,000 / 4,000 tokens, whole results | answerable cases | the first result that answers ends within the budget, as the retrieval benchmark measures it ([Within a token budget](retrieval-benchmark.md#within-a-token-budget), #575) |
| recall within 1,000 / 2,000 / 4,000 tokens, text cut | answerable cases | the text cut at the budget answers: a result within it answers, or the result the budget cuts answers from its part within it (`cut_answers`) |
| facts found | answerable cases | the share of the case's facts the returned text holds, averaged over the cases |

[^context]: Tools return very different amounts of text, so a hit costs a different number of
    tokens in each.

`TextResult.of(tool, rows)` aggregates one tool's rows overall, by question kind and by project,
and `results_table` renders tools side by side.

### Facts found

Facts found is a second signal, independent of the sections. A fact is found when at least 75%
(`FACT_SHARE`) of its content words are in the text the tool returned: words normalized as above,
a fixed list of stopwords left out, a plural `s` cut.

!!! warning "It is lexical"
    A fact the docs phrase otherwise can be missed, and a lot of text finds more facts by chance.
    So the calibration gives both bounds on ExactDocs' results:

    - the share of facts in the expected sections' own text (about the most a tool can reach);
    - the share in the results of another question of the same version (what text that does not
      answer reaches).

### Version-neutral results

Most text of a pinned version is the same in the other pinned versions of its project. So most
results, right or wrong, are version-neutral, and a result of another version is caught as wrong
only where the text changed.

- The text scorer's wrong-version rate is in effect a lower bound of the rate chunk-ID scoring
  would give.
- The version-neutral share says how much of what a tool returned no check on the text alone can
  attribute.

## Calibration

`just text-bench` checks the text scorer against chunk-ID scoring on ExactDocs' own results. For
each chunking configuration it:

1. imports the corpus as the ingestion benchmark does;
2. asks every golden question with BM25 in its project's library;
3. reads each result back by its chunk ID and keeps the chunk's content as the result's text;
4. scores the results both ways, chunk IDs with the retrieval benchmark's rule
   (`golden_run.held_match`).

A decision is where an expected section of an answerable case is in the top 10 (its rank), or that
it is not. The two scorings agree on a decision when they give the same rank, or both a miss.

!!! info "The criterion"
    98% agreement at `default`, the chunking ExactDocs ships (`MIN_AGREEMENT`,
    `GATED_CHUNKING`). Below it the command exits with 1.

The report (`text-scorer.json` and `text-scorer.md`, in `reports/evals/` or `--out`) also gives:

- the agreement on hit or miss alone, whatever the rank;
- the agreement on the same results rendered as plain text (the Markdown rendered and the tags
  dropped), as a tool that renders its results returns them;
- the agreement on each case's wrong-version decision;
- the agreement at each threshold from 0.5 to 1, on the results as returned and as rendered;
- both scorings' metrics side by side, the text-only metrics, and every disagreement with what the
  result at the earlier rank is.

### The recorded calibration

`packages/exactdocs/evals/results/text-scorer.json` and `text-scorer.md`, on the whole reviewed
golden set (321 cases, 404 decisions), about two minutes per chunking on 4 CPUs:

| Chunking | Same rank | Hit / miss | Rendered as plain text | BM25 recall@5<br/>text (chunk ID) |
|---|---|---|---|---|
| `default` | **99.8%** | 100.0% | 99.8% | 87.6% (87.6%) |
| `h6` | 99.8% | 100.0% | 99.8% | 85.8% (85.8%) |
| `h2` | 99.8% | 100.0% | 99.5% | 89.1% (89.1%) |
| `merge-400` | 99.5% | 99.8% | 99.5% | 87.6% (87.6%) |

- The criterion is met at `default`, and the agreement is above it at every chunking.
- Both scorings take the same wrong-version decision on every case at every chunking: BM25 returns
  nothing of another version, and no result's text is only in another version.
- At `default`:
    - 72% of BM25's results are version-neutral;
    - its ten results hold 3,464 tokens of context on average, 656 of them up to the first hit;
    - they hold 87% of the cases' facts, where the expected sections' own text holds 81% and
      another question's results 25%.
- Both scorings give the same recall within each token budget at every chunking (#575, whole
  results): at `default`, 78.3%, 88.8% and 93.6% within 1,000, 2,000 and 4,000 tokens; at `h2`,
  whose chunks are twice as long, 49.1%, 76.8% and 89.1%.

### Why 0.8 and 5 words

The threshold is 0.8 because of the sweep:

- Below it, results of other articles that share part of a section's text count as hits. At
  `default`, agreement is 98.8% at 0.7 and 97.5% at 0.5.
- Above it, the results as returned agree as well, but rendered ones less (99.5% at 0.9, 90.3% at
  1), since a rendering loses a little text.
- Shingles of 5 words are the usual size for near-duplicate text. In trial runs, 3 to 9 words moved
  the agreement at 0.8 by less than a point.

### What #503 and #501 changed

Until #503, chunk-ID scoring counted a coarser chunk only when it was named after a parent of the
expected section. The calibration showed what that missed:

- At `h2` and `merge-400` the two scorings agreed on only 93.2% and 90.9% of the decisions.
- In 25 of `h2`'s 26 disagreements and 33 of `merge-400`'s 35, the returned chunk held the
  expected section next to another one (a section with its subsections; small sections merged with
  the next).
- So did one at `default`: Starlette's 1.0.0rc1 release notes are longer than 4,000 characters, so
  they are cut again at their `####` headings, and the chunk `1.0.0rc1 > Removed` also holds
  `Fixed`.

Chunk-ID scoring now reads what each chunk holds, and BM25's recall@5 at `h2` and `merge-400` went
from 76.0% and 74.2% to the 82.8% and 81.7% the text gives. Then #501 counted a hit on any section
a case lists (the recall@5 column above), which moved both scorings alike.

### What still disagrees

- **The same text in two articles.** TanStack Query v5.90.3 explains streaming with
  `useSuspenseQuery` in `guides/suspense.md` and again, nearly word for word, in
  `guides/advanced-ssr.md`.
    - BM25 returns the second at rank 1 and the expected one at rank 7; the text scorer finds the
      expected section's text at rank 1.
    - Text alone cannot say which article a result came from; a tool that returns it does answer
      the question.
    - This is the one disagreement at `default`, `h6` and `h2`.
- **A part of a section that runs past it.** At `merge-400`, Electron's chunk
  `Signing & notarizing macOS builds > Signing Mac App Store applications`, a subsection of the
  expected section, was merged with the start of the next section. Chunk-ID scoring counts it as
  part of the expected section; the text scorer does not, since less than 80% of its text is.

## The JSON report

`text-scorer.json` (`schema_version` 2).

??? info "Fields of `text-scorer.json`"
    - `golden` (the golden set's fingerprint), `cases`, `projects`;
    - `corpus`: every pinned version's commit;
    - `environment`: as the retrieval benchmark records it;
    - `scorer`: `shingle_words`, `threshold`, `fact_share`, `min_agreement`, `gated_chunking`;
    - per chunking, in `calibrations`:
        - `agreement` and `rendered_agreement`, each `decisions`, `agreed`, `rate`,
          `hit_miss_rate`[^held];
        - `wrong_version_agreement`;
        - `sweep`: `threshold`, `rate`, `rendered_rate`;
        - `disagreements`: `case`, `section`, `chunk_id_rank`, `text_rank`, `why`;
        - `chunk_id`: the retrieval benchmark's metrics;
        - `text`: the same scored from text, with the metrics only text gives;
        - `facts_in_expected_sections` and `facts_in_other_results`.

[^held]: Version 1 also had `held_agreement`, the agreement with a rule that counted held
    headings, which chunk-ID scoring does itself since #503.

Like the other benchmarks, it runs by hand, not in CI. Run it when the matcher, the parser or the
chunker changes, and record it in the same pull request. Pull request CI runs the quick tests
(`tests/evals/test_text_match.py`, `test_text_bench.py`, `text_scorer.feature`) on small local
corpora.
