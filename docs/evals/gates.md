# Gates and the baseline

!!! abstract "TL;DR"
    - The wrong-version rate must be 0 for every mode that ran, whatever its recall.
    - BM25's recall@5 may not drop more than 2 points below the baseline, and the stored baseline
      only moves up.
    - A mode becomes a default only when it beats BM25's recall@5 by at least 5 points with a
      wrong-version rate of 0. Only `bm25` qualifies today.
    - Changing the dataset resets the baseline, but `develop`'s dataset still runs against
      `develop`'s baseline, so a reworded question cannot hide a regression.

## Gates

| Gate | What it checks |
|---|---|
| wrong version | no mode that ran returns a result of another version |
| recall drop | BM25's recall@5 is at most 2 points below the baseline |
| ratchet (`--ratchet`) | the stored baseline only goes up, and never above what the run measures |
| same dataset | the baseline was recorded for this dataset |
| agentic trace | no agentic run reads outside the version asked for |
| errors | no question's search raises |
| default | a mode becomes a default only with a 5-point margin over BM25 |

### Wrong version

**Wrong-version rate must be 0 for every mode that ran**, whatever its recall. One result of
another version fails the suite.

### Recall drop

**recall@5 may not drop more than 2 points below the baseline.**

- The baseline at a release is the `baseline.json` committed in the tagged tree.
- When you check a branch, it is the one you pass with `--baseline` (such as `develop`'s).
- A drop fails the suite for BM25 and is a warning for the report-only modes.
- A gating mode with no baseline entry is a warning (its recall is then not gated).

### Ratchet

**The stored baseline only moves up** (`--ratchet`).

- Checked against `develop`'s copy, the branch's `baseline.json` may not store a lower BM25
  recall@5 than `develop`'s.
- A value it raises must be what the run measures: a stored recall@5 above the measured one fails.
- The release passes `--ratchet` with no `--baseline`, so the committed file is compared with
  itself. The check that remains is that it was recorded for this dataset.

### The rest

- A run compares with another baseline only **on the same dataset**. When the dataset changed,
  see [Changing the dataset](#changing-the-dataset).
- **No agentic run may read outside the version asked for**, from its trace
  ([Agentic traces](suite.md#agentic-traces)).
- A question whose search raises fails the suite.

### Becoming a default

**A mode becomes a default only when the suite shows it beats BM25's recall@5 by at least
5 points with a wrong-version rate of 0.**

- The report marks such a mode `eligible_as_default`. Changing the default order
  (`DEFAULT_MODE_ORDER`) without that is not accepted.
- It holds only `bm25` today.
- For `hybrid`, only a real embedding model's run counts (#245), never the term-hash stand-in's,
  whose report says `not judged (offline embedding)`.
- The same holds for `hybrid_hyde`. The release runs it only on a stand-in LLM
  ([Tiers](suite.md#provider)), so it needs a run with a real LLM and embedding model before it
  can become a default.

## The baseline

`packages/exactdocs/evals/retrieval_eval/baseline.json` holds, for each mode that ran:

- recall@1/5/10, MRR and the wrong-version rate (no latency, which depends on the machine);
- the `dataset` fingerprint they were measured on.

The release gates on the copy committed in the tagged tree. No pull request job checks it, so a
reviewer checks a change to it in the diff.

To hold a branch to `develop`'s bar, fetch `develop`'s `baseline.json` and `dataset.yaml` and run:

```bash
just eval --baseline develop.json --ratchet --reference-dataset develop.yaml
```

A change that improves ranking refreshes the baseline in the same pull request, where the diff
shows the new numbers:

```bash
just eval --write-baseline
```

## Changing the dataset

The fingerprint (`sha256:...` in `baseline.json`) is a hash of what the dataset states: each
case's question (`inputs`, defaults left out) and the version, article and heading path of each
section it expects, in order, and whether it is an alternative (#501).

| Keeps the fingerprint | Changes it |
|---|---|
| renaming, reordering or commenting cases | adding or removing a question |
| a new field with a default in the dataset's models | changing a question or an expected section |
| | marking a section as an alternative |

Numbers measured on different datasets are not comparable: harder questions lower recall without
anything getting worse. So:

1. Change `dataset.yaml` (see [The dataset](suite.md#the-dataset)).
2. Run `just eval --write-baseline` and commit the new `baseline.json` in the same pull request.
   It records the new fingerprint and the recall measured on the new dataset, which may be lower.
3. Check against `develop`'s baseline (`--baseline develop.json --ratchet
   --reference-dataset develop.yaml`, the run to do before the pull request). `develop`'s
   baseline has another fingerprint, so the baseline is **reset**:
    - the drop gate compares with the branch's `baseline.json`, and the ratchet against `develop`
      is off; once the pull request is merged it starts again from the new baseline;
    - the branch's stored recall@5 must be exactly what the run measures, neither above nor below,
      since it becomes the next bar;
    - **`develop`'s dataset is still run**, with the branch's code, and gated against `develop`'s
      baseline as usual (`--reference-dataset`; its summary is *Retrieval eval on the reference
      dataset*). A question of the old dataset whose version or section the fixture no longer has
      fails the run instead of being skipped. So rewording or adding a question cannot hide a
      ranking regression: the old questions still catch it;
    - the reset is reported as a warning annotation (*Eval baseline reset*) and in the summary
      (**Baseline reset: the dataset changed (...)**).

!!! failure "was recorded for dataset ..., not this one"
    If `baseline.json` was not rewritten, its fingerprint is not the dataset's, and a run with
    `--ratchet` (the release's included) fails with this message.

### Changing the fixture

**The fixture is not part of the fingerprint.** A change to the fixture docs repository
(`packages/exactdocs/tests/fixtures/docs-repo`), such as a new distractor article, is gated like a
ranking change:

- recall@5 may not drop more than 2 points below the baseline;
- there is no reset path (a reset still runs `develop`'s dataset against `develop`'s baseline, on
  the new fixture).

So a fixture change has to keep BM25's recall@5 within those 2 points.
