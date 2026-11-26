# Agent results

!!! abstract "TL;DR"
    - First run on 2026-11-24: 60 golden questions, two agent models, each with no docs (`none`)
      and with only the ExactDocs MCP tools (`exactdocs`), judged by `glm-5.3`.
    - With ExactDocs, accuracy rose significantly for both: `gpt-oss:120b` from 13.3% to 40.0%
      (+26.7 points [+15.0, +40.0], p = 7.6e-05; 43.3% in the first run), `kimi-k3` from 33.3% to
      83.3% (+50.0 points [+38.3, +63.3], p = 9.3e-10; 85.0% in the first run).
    - With ExactDocs two answers of the 120 were true of another version only; without, 15 of
      `gpt-oss:120b`'s 60 answers and 5 of `kimi-k3`'s were.
    - Grounded Docs, added on 2026-11-25 on the same questions: as accurate as ExactDocs on these
      60 (`gpt-oss:120b` 45.0%, +5.0 points [-5.0, +16.7], p = 0.39; `kimi-k3` 81.7%, -1.7 points
      [-11.7, +8.3], p = 0.77), with fewer tool calls, and 2 answers wrong for the version.
    - Tools that take loose arguments (#573, 2026-11-25): asked again, `gpt-oss:120b`'s ExactDocs
      runs hit a tool error in 1 of 60 instead of 21, and one ended without an answer instead of
      two; its accuracy did not change (41.7% against 43.3%, 5 gained, 6 lost, p = 0.77).
    - Search results grouped by article (#575) and `read_article`'s text (#588), 2026-11-25: asked
      again, both models were as accurate with ExactDocs as before (`gpt-oss:120b` 40.0% against
      41.7%, p = 0.77; `kimi-k3` 83.3% against 85.0%, p = 0.75) with significantly fewer tool calls
      (4.0 against 4.7 and 4.5 against 5.5 a question); `kimi-k3` also wrote 10% fewer output
      tokens (p = 0.012).
    - Context7's arm is built but has not run: no API key, and Upstash's terms forbid publishing
      its numbers without permission.
    - The judge is not checked against hand labels yet, and Ollama Cloud's usage limit kept the run
      at 60 questions.

Does a coding agent answer version-specific questions better with ExactDocs than from what it
already knows, or than with another documentation tool, and what does that cost in time and
tokens? The agent benchmark (#348, #495) asks the same model each [golden-set](golden-set.md)
question with each **documentation arm**:

- **no documentation** (arm `none`);
- **only the ExactDocs MCP tools** (`exactdocs`);
- **only Grounded Docs' tools**, over its own index of the same pinned versions (`grounded-docs`);
- **only the official Context7 MCP server's tools** (`context7`).

An LLM judge, blind to the arm, grades every answer against the case's reference and facts.

!!! warning "The `context7` arm has not run"
    It is built and tested (against the official server, `@upstash/context7-mcp` 4.5.0, with a
    stand-in of Context7's API), but it needs a Context7 API key, which this run did not have, and
    Upstash's terms forbid publishing benchmark results without its permission. No Context7 number
    will be published here until it is given
    ([Terms of service](../evals/context7.md#terms-of-service)).

**The first run** (2026-11-24):

| | |
|---|---|
| Agent models | `gpt-oss:120b` (OpenAI)[^cutoff] and `kimi-k3` (Moonshot AI), from different vendors |
| Judge | `glm-5.3` (Z.ai) |
| Questions | 60 golden questions (2 of each kind in each project, a seeded stratified sample) |
| Answers | 240 |

[^cutoff]: Its model card gives a June 2024 knowledge cutoff, before the newest pinned version of
    every project.

With the ExactDocs tools (both models' answers were asked again on 2026-11-25, see *Tools that
take loose arguments* and *Search results grouped by article* below; the tables at the end hold
the newest):

- **Accuracy rose for both models, significantly.**

    | Model | `none` | `exactdocs` | Difference | Gained / lost | McNemar p |
    |---|---|---|---|---|---|
    | `gpt-oss:120b` | 13.3% [5.0, 21.7] | 43.3% [31.7, 56.7] | +30.0 points [+18.3, +43.3] | 19 / 1 | 2.1e-05 |
    | `kimi-k3` | 33.3% [21.7, 45.0] | 85.0% [75.0, 93.3] | +51.7 points [+40.0, +65.0] | 31 / 0 | 4.7e-10 |

- **No answer was true of another version only.** Without documentation the judge flagged 15 of
  `gpt-oss:120b`'s 60 answers (25%) and 5 of `kimi-k3`'s (8%) as stating what holds for another
  version; with ExactDocs, none of either model's.
- **More right refusals.** On the 10 `unanswerable` questions, `kimi-k3` said the documentation
  does not cover it 9 times with ExactDocs against 2 without; `gpt-oss:120b` 4 against 2. Neither
  model refused an answerable question with ExactDocs.
- **What it costs depends on the model.**
    - `gpt-oss:120b` took twice as long (2.9 s to 6.0 s a question on average, p95 5.1 s to
      10.3 s; +3.1 s [+2.4, +3.7], p = 0.0001) and wrote 21% more output tokens (745 to 901,
      thinking included; p = 0.002).
    - `kimi-k3` was not slower: its mean fell from 19.1 s to 14.6 s and its output from 1,913 to
      1,318 tokens, neither significant (p = 0.19 and 0.073). Without documentation it thinks at
      length about versions it does not know (p95: 56 s and an estimated 5,400 thinking tokens);
      with it, the median rose (9.8 s to 12.5 s) and the long tail shrank (p95 33 s).
    - Both made about 5.5 tool calls a question. What the tools returned grew the input from
      about 200 tokens to 38,000 (`kimi-k3`) and 50,000 (`gpt-oss:120b`) a question: the bulk of
      the cost on a per-token price.
- **The judge is strict.** `correct` needs every fact the case lists, and the facts often go
  beyond the literal question; a brief, right answer is often `partially_correct` (24 of
  `gpt-oss:120b`'s 60 answers with ExactDocs). That lowers the accuracy of both arms alike.

**Grounded Docs** (2026-11-25): the same 60 questions and the same two agents and judge, added to
the run with `--resume` (120 answers; Grounded Docs 3.4.1 with full-text search, its default with
no model, as ExactDocs ran with BM25). With Grounded Docs' tools:

- **As accurate as ExactDocs on these 60 questions; far above no documentation.**

    | Model | `grounded-docs` | Against `none` | Against `exactdocs` | Gained / lost against `exactdocs` |
    |---|---|---|---|---|
    | `gpt-oss:120b` | 45.0% [31.7, 56.7] | +31.7 points, p = 1.9e-06 | +3.3 points [-8.3, +15.0], p = 0.58[^first-exactdocs] | 7 / 5 |
    | `kimi-k3` | 81.7% [71.7, 91.7] | +48.3 points, p = 1.9e-09 | -3.3 points [-13.3, +5.0], p = 0.51 | 3 / 5 |

    Neither difference between the two tools is significant, and their intervals span several
    points either way: 60 questions cannot tell them apart.

    [^first-exactdocs]: Against the ExactDocs answers asked again in #573's run. Against the
        first run's: +1.7 points [-8.3, +11.7], p = 0.75, 5 / 4.

- **Two answers wrong for the version.** The judge flagged 2 of `gpt-oss:120b`'s 60 answers, against
  none with ExactDocs in the first run (one in #573's); `kimi-k3` had none.
    - One put a deprecation in the wrong Electron release; one cited later Pydantic docs while
      rightly saying v2.5.3 does not cover the question.
    - The agents sometimes searched Grounded Docs with an X-range (`4.36.x`, `5.x`: 22 of its 238
      searches), which can match a newer indexed version of the range than the one asked;
      ExactDocs takes one exact version.
- **Right refusals on `unanswerable` questions:** `kimi-k3` 7 of 10 (9 with ExactDocs),
  `gpt-oss:120b` 5 of 10 (4 with ExactDocs); no answerable question refused.
- **Fewer calls and tokens.**
    - About 3.5 tool calls a question, against 5.5 with ExactDocs (4.7 for `gpt-oss:120b` in
      #573's run).
    - Output tokens 24% lower for `kimi-k3` (-310, p = 0.0001). For `gpt-oss:120b`, 7% lower
      against #573's ExactDocs answers, not significant (-56 [-144, +47], p = 0.25); 13% against
      the first run's (-117 [-198, -31], p = 0.0097).
    - Input tokens: 16,065 a question for `kimi-k3` against 37,754 (p = 0.0001); 41,413 for
      `gpt-oss:120b` against 43,023 (not significant; its p95, 177,000, is a few questions it
      searched 10 to 16 times, each answer a list of passages, before answering or reaching the
      request limit).
    - Each `search_docs` result carries the matching passage with the context Grounded Docs
      assembles around it, so the agents read fewer pages.
- **Wall time is not compared.** The `grounded-docs` answers ran a day after the first run, on a
  different day of Ollama Cloud: their 4.2 s and 8.4 s a question (6.0 s and 14.6 s with ExactDocs
  then; 5.3 s for `gpt-oss:120b`'s ExactDocs answers of #573's run, five hours after them) mix the
  tool with the provider's load. The time columns below are given, not read.
- *Read the answer* (8% and 10%) counts only whole pages read with `read_page` (22 of the 120
  answers); most answers came from `search_docs` passages, which do not count, as ExactDocs'
  snippets do not. It is not comparable with ExactDocs' 36% and 52%.

**Tools that take loose arguments (#573)** (2026-11-25): in the first run, `gpt-oss:120b` hit a tool
error in 21 of its 60 ExactDocs runs, 20 of them on an argument the tools refused (an empty
`query` of `resolve-library-id` 17 times, `path_prefix` on `search_docs` 4 times, `limit: 1000`,
a library's name instead of its ID). The harness ends a run whose tool fails twice, and both of its
`no_answer` runs ended that way. #573 made the tools take those arguments: an empty optional one
counts as not given, a number out of range is clamped, a name is resolved to its ID, `search_docs`
takes `path_prefix`, and a missing path names the closest ones. Its 60 ExactDocs answers were then
asked again, everything else kept (`--resume` on the other 300):

| `gpt-oss:120b`, `exactdocs` | First run | #573's run |
|---|---|---|
| Accuracy | 43.3% [31.7, 56.7] | 41.7% [30.0, 53.3] |
| Against `none` | +30.0 points [+18.3, +43.3], p = 2.1e-05 | +28.3 points [+16.7, +40.0], p = 4.0e-05 |
| `grounded-docs` against it | +1.7 points [-8.3, +11.7], p = 0.75 | +3.3 points [-8.3, +15.0], p = 0.58 |
| No answer | 2 | 1 |
| Runs with a tool error (calls) | 21 (26) | 1 (2) |
| Tool calls a question | 5.5 [4.8, 6.2] | 4.7 [4.2, 5.3] |
| Input tokens a question | 50,433 [41,271, 60,654] | 43,023 [34,322, 54,096] |
| Output tokens a question | 901 [806, 1,008] | 839 [752, 940] |
| Wrong for the version | 0 | 1 |

- **The errors are gone, the accuracy is not up.** 51 of the 60 runs sent `resolve-library-id` an
  empty `query` and all 60 sent `search_docs` an empty `path_prefix` (it is in the schema now);
  each would have failed before. Against the first run's answers, 5 questions were gained and 6
  lost (McNemar p = 0.77): what changed is the sampling of a model at medium thinking, not the
  tools. Of the 21 questions whose first run hit an error, 8 are right now, against 6.
- **The one error left is a path that does not exist.** On "How do I create a model from an ORM
  object?" (Pydantic v1.10.22) it asked `read_article` for `tmp_examples/models_orm_mode.md`. The
  error named `docs/usage/models.md` first, but it tried `docs/tmp_examples/models_orm_mode.md`
  next, and that second miss ended the run (`no_answer`), as in the first run.
- **One answer wrong for the version.** On "Which HTTP client library does TestClient need now?"
  (Starlette 1.10.0) it answered `httpx` after one search, without reading a section; the version
  uses `httpx2`.
- **`read_article` still gave it no text.** Its structured content holds the article's metadata,
  and pydantic-ai, which runs the agents, hands the model the structured content instead of the
  text (#587, fixed in #588). This run measures #573 alone; the next one will have both.

**Search results grouped by article (#575)** (2026-11-25): `search_docs` now returns its results
grouped by article, the best article first ([Retrieval results](retrieval.md#grouped-by-article-575)),
and `read_article` hands the model its text (#588). Both models' 60 `exactdocs` answers were asked
again, the other 240 kept (`--resume`):

| | `gpt-oss:120b` before | after | `kimi-k3` before | after |
|---|---|---|---|---|
| Accuracy | 41.7% [30.0, 53.3] | 40.0% [28.3, 51.7] | 85.0% [75.0, 93.3] | 83.3% [73.3, 91.7] |
| After against before | | -1.7 points [-13.3, +8.3], 5 / 6, p = 0.77 | | -1.7 points [-11.7, +8.3], 4 / 5, p = 0.75 |
| Against `none` | +28.3 points, p = 4.0e-05 | +26.7 points [+15.0, +40.0], p = 7.6e-05 | +51.7 points, p = 4.7e-10 | +50.0 points [+38.3, +63.3], p = 9.3e-10 |
| `grounded-docs` against it | +3.3 points, p = 0.58 | +5.0 points [-5.0, +16.7], p = 0.39 | -3.3 points, p = 0.51 | -1.7 points [-11.7, +8.3], p = 0.77 |
| Wrong for the version | 1 | 2 | 0 | 0 |
| Runs with a tool error (calls) | 1 (2) | 1 (2) | 2 (2) | 1 (1) |
| Tool calls a question | 4.7 [4.2, 5.3] | 4.0 [3.5, 4.7] | 5.5 [4.8, 6.4] | 4.5 [4.0, 5.0] |
| Input tokens a question | 43,023 [34,322, 54,096] | 50,381 [34,420, 72,490] | 37,754 [28,714, 49,149] | 33,107 [28,356, 38,938] |
| Output tokens a question | 839 [752, 940] | 824 [726, 945] | 1,318 [1,138, 1,522] | 1,186 [1,049, 1,346] |

*Before* is the recorded run before this one: `gpt-oss:120b`'s answers of #573's run, `kimi-k3`'s of
the first run. Gained / lost and p: McNemar's test on the same 60 questions.

- **Accuracy did not change measurably.** Each model lost one question net (5 gained and 6 lost,
  4 and 5), the sampling of a model at medium thinking, as in #573's re-run; 60 questions cannot
  show a change this small either way. ExactDocs stays far above no documentation and level with
  Grounded Docs.
- **Fewer tool calls, significantly.** `gpt-oss:120b` -0.67 a question [-1.23, -0.12] (p = 0.022),
  `kimi-k3` -1.05 [-1.70, -0.47] (p = 0.0005), by a paired permutation test.
    - `kimi-k3` read 38 fewer chunks with `read_chunk` (72 against 110) and searched 10 fewer
      times (104 against 114).
    - `gpt-oss:120b` opened 17 fewer articles with `view_article` (27 against 44), whose text it
      read when `read_article` gave it none, and called `read_chunk` no more (9 before).
    - Grounded Docs still takes fewer: 3.6 and 3.45 a question.
- **Tokens.** `kimi-k3` wrote 132 fewer output tokens a question [-234, -36] (10%, p = 0.012); its
  input fell by 4,648, not significantly (p = 0.25). `gpt-oss:120b`'s output did not change
  (p = 0.65), and its input rose by 7,358, not significantly (p = 0.37; its p95, 143,000, is a few
  questions it searched or read at length).
- **Two answers wrong for the version, both `gpt-oss:120b`'s.** One put Electron's
  navigation-history deprecation in v38 instead of v32. One answered how to `.encode()` a Zod
  v4.0.17 schema, which that version cannot do (codecs came in 4.1): an `unanswerable` case.
  `kimi-k3` had none.
- **The one tool error left for `gpt-oss:120b` is a version's name.** On a Starlette 1.10.0
  question it called `search_docs` with `ref` `v1.10.0` twice. ExactDocs names that version
  `1.10.0`, and the error ("no index for /encode/starlette@v1.10.0") did not list the versions it
  has, so the second miss ended the run (`no_answer`). `kimi-k3`'s one error was an article path
  that does not exist; the error named the closest paths and it answered right.
- **More than the grouping changed.** #575's grouping and #588's `read_article` text both reached
  these answers, and `kimi-k3`'s answers before were the first run's, so #573's tools are new to
  it as well. This run cannot tell their effects apart.
- **Wall time is not compared**: these answers ran on another evening of Ollama Cloud.

## Read this first

- **Three runs in one table.** The `none` answers are the run of 2026-11-24 (ExactDocs at
  `5394cd5aa246`); the `grounded-docs` answers were added on 2026-11-25 (at `c6188f4fccce`), and
  both models' `exactdocs` answers asked again that evening with #575's grouped results (at
  `345de89ced05`), each by `--resume`, which asks only the questions the checkpoint does not hold.
  The agents, judge, prompt, instructions apart from the tool's name, request limit and thinking
  setting are the same. Accuracy and tokens compare across the runs; wall time does not.
- **Open-weight models, served by Ollama Cloud.** The agents and the judge are open-weight models
  as [Ollama Cloud](https://ollama.com/) serves them (its API at `https://ollama.com/v1`), not the
  vendors' own APIs; how it quantises and serves them is not ours to see. Hosted frontier models
  have not run yet.
- **The judge is not checked against people yet.** The accuracies rest on one LLM judge
  (`glm-5.3`, a third vendor) that has not been compared with hand labels: the agreement
  criterion of #348 (at least 50 hand-labelled answers) is still open, and until it is met a
  difference of a few points can be the judge's. The answers are in the JSON report for
  labelling (`just agent-bench sample`).
- **Thinking tokens are estimated.** Ollama returns a model's thinking as text and counts it
  inside the output tokens, with no separate count. The thinking tokens below are an estimate:
  each response's output tokens times the thinking's share of the characters it produced. The
  output tokens are as reported, thinking included.
- **No price.** Ollama Cloud bills by plan, not per token, so USD is *unpriced* (`null`), not 0.
- **Wall time is Ollama Cloud's.** It includes the provider's latency and queueing at the time of
  the run, with 3 questions in flight; the time lost to retried requests is left out. Compare the
  arms with each other, not with another day's run.
- **60 questions, not 321.** Ollama Cloud's session usage limit stopped the planned 90-question
  sample twice (below); the recorded run is its complete 2-per-stratum part. With 10 questions per
  kind and 12 per project, those intervals are wide; the overall differences above are not.
- **The golden set has its own flaws** ([its review](golden-set.md#the-independent-review)): in
  the reviewed sample no reference answer was wrong, but 3 cases had facts their sections did not
  state, and 17 lacked a section that answers as well; most cases are not reviewed. A missing
  section lowers *Read the answer* (which counts only the listed sections), not accuracy; a
  flawed fact weighs on both arms alike.

## The run

<!-- bench:agent-run -->
- Started 2026-11-25T22:04:39+00:00; ExactDocs `0.0.0.post140.dev0+eee1e310` at `345de89ced05`. 347 of the answers were kept from an earlier run of the same command (`--resume`), at its commit and time.
- Agents: `ollama:gpt-oss:120b`, `ollama:kimi-k3`; judge `ollama:glm-5.3`; served by ollama at `https://ollama.com/v1`.
- Arms: `none`, `exactdocs`, `grounded-docs`; configurations of `exactdocs`: `bm25`; of `grounded-docs`: `full-text`.
- `exactdocs (bm25)`: exactdocs serve --stdio.
- `grounded-docs (full-text)`: @arabold/docs-mcp-server 3.4.1 (read-only, HTTP).
- Cases: 60 (2 per kind and project, seed 495); at most 20 model requests per question; thinking: medium; 3 questions at a time; 6 retries of a failed request.
<!-- /bench -->

- The judge ran with its model's default thinking.
- The agents ran with `--thinking medium` (sent as `reasoning_effort`; the models think whatever
  it says).
- ExactDocs ran with BM25, its default with no model.

The run was planned on 90 questions (3 per kind and project, seed 495):

```bash
OLLAMA_BASE_URL=https://ollama.com/v1 OLLAMA_API_KEY=... just agent-bench run \
  --agent-model ollama:gpt-oss:120b --agent-model ollama:kimi-k3 --judge-model ollama:glm-5.3 \
  --arm none,exactdocs --retrieval bm25:mode=bm25 --thinking medium \
  --per-stratum 3 --concurrency 3 --report reports/evals/agent-bench.json
```

How it went:

| Time (UTC) | What happened |
|---|---|
| 08:16 | the run started |
| 08:40 | after about 155 answers, every request got `429 ... reached your session usage limit`[^429] |
| 11:08 | the limit lifted; `--per-stratum 2 --resume` asked again what had failed |
| 11:29 | the 60-question sample finished with no provider error left[^resumed] |
| later | extending it to 90 with `--per-stratum 3 --resume`<br/>hit the limit again after 17 more answers |

[^429]: Recorded as provider errors, not wrong answers.
[^resumed]: The first two of each stratum's three draws: the same seed.

On the plan used, an Ollama Cloud session held about 155 answers with their judgements. The
90-question sample (about 50 answers short) and all 321 questions (about six more sessions) are
left for a later run, which `--resume` lets span sessions.

Each question's four answers (two models, two arms) were asked together, so both arms of a
question ran in the same session, except for one question whose answers straddle the limit.

The `grounded-docs` arm was added on 2026-11-25 with the first run's 240 answers as the
checkpoint (`reports/evals/agent-bench.rows.jsonl`), so only its 120 answers were asked, from 09:37
to 09:50 UTC, with no provider error (the start time above is this run's):

```bash
OLLAMA_BASE_URL=https://ollama.com/v1 OLLAMA_API_KEY=... just agent-bench run \
  --agent-model ollama:gpt-oss:120b --agent-model ollama:kimi-k3 --judge-model ollama:glm-5.3 \
  --arm none,exactdocs,grounded-docs --retrieval bm25:mode=bm25 --grounded-docs full-text \
  --thinking medium --per-stratum 2 --concurrency 3 --report reports/evals/agent-bench.json --resume
```

`gpt-oss:120b`'s `exactdocs` answers were asked again on 2026-11-25 (#573), from 14:41 to 14:48
UTC with no provider error, with the recorded run's other 300 answers as the checkpoint. The same
command with `--resume`; ExactDocs ran this branch's tools:

```bash
OLLAMA_BASE_URL=https://ollama.com/v1 OLLAMA_API_KEY=... just agent-bench run \
  --agent-model ollama:gpt-oss:120b --agent-model ollama:kimi-k3 --judge-model ollama:glm-5.3 \
  --arm none,exactdocs,grounded-docs --retrieval bm25:mode=bm25 --thinking medium \
  --per-stratum 2 --seed 495 --concurrency 3 --max-retries 6 --report reports/evals/agent-bench.json --resume
```

Both models' `exactdocs` answers were asked again on 2026-11-25 (#575), at `345de89ced05`, with
the recorded run's `none` and `grounded-docs` answers (240) as the checkpoint, by the same command
(`--arm none,exactdocs,grounded-docs --retrieval bm25:mode=bm25 --thinking medium --per-stratum 2
--seed 495 --concurrency 3 --resume`):

| Time (UTC) | What happened |
|---|---|
| 20:16 | the run started; the pinned versions were imported |
| 20:33 | after 107 answers, every request got `429 ... reached your session usage limit`; the 13 left were recorded as provider errors, not wrong answers |
| 22:04 | the limit lifted; `--resume` asked those 13 (all Zod questions), with no provider error |

The golden set's fingerprint changed in #601 (`sha256:a00997851150e3b0` to
`sha256:100484c7ccdb1b89`): one Pydantic case's expected heading lost its `{#config-both}`. The
sample is the same 60 cases with the same questions, references and facts; that case is not one
of them.

- Grounded Docs searched the full-text index `just grounded-bench` had built of the 15 pinned
  versions (the same files the ExactDocs importer takes at the pinned commits), in its read-only
  mode.
- The agents were offered `search_docs`, `read_page`, `list_pages`, `list_libraries` and
  `find_version`; not `fetch_url`, which reads any web page.
- The library names it lists are the project IDs (`tanstack-query`). A search for
  `TanStack Query` (or `@tanstack/react-query`) was answered "not found, did you mean
  tanstack-query?", and every such question went on with the right name.

<!-- bench:agent -->
## Quality

| Agent model | Arm | Accuracy | Correct | Partial | Wrong | Refused | No answer | Errors | Wrong for the version | Refused, answerable | Correct refusals, unanswerable | Read the answer | Read another version | Tool calls/q |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 13.3 % [5.0, 21.7] | 6 | 18 | 34 | 2 | 0 | 0 | 15 (25.0 % [15.0, 36.7]) | 0 (0.0 % [0.0, 0.0]) | 2 (20.0 % [0.0, 50.0]) | n/a (no tools) | 0 | 0.0 [0.0, 0.0] |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 40.0 % [28.3, 51.7] | 19 | 29 | 6 | 5 | 1 | 0 | 2 (3.3 % [0.0, 8.3]) | 0 (0.0 % [0.0, 0.0]) | 5 (50.0 % [20.0, 80.0]) | 28.0 % [16.0, 40.0] | 0 | 4.0 [3.45, 4.683] |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 45.0 % [31.7, 56.7] | 22 | 26 | 6 | 5 | 1 | 0 | 2 (3.3 % [0.0, 8.3]) | 0 (0.0 % [0.0, 0.0]) | 5 (50.0 % [20.0, 80.0]) | 8.0 % [2.0, 16.0] | 0 | 3.6 [2.817, 4.533] |
| `ollama:kimi-k3` | none | 33.3 % [21.7, 45.0] | 18 | 20 | 17 | 5 | 0 | 0 | 5 (8.3 % [1.7, 16.7]) | 3 (6.0 % [0.0, 14.0]) | 2 (20.0 % [0.0, 50.0]) | n/a (no tools) | 0 | 0.0 [0.0, 0.0] |
| `ollama:kimi-k3` | exactdocs (bm25) | 83.3 % [73.3, 91.7] | 41 | 8 | 2 | 9 | 0 | 0 | 0 (0.0 % [0.0, 0.0]) | 0 (0.0 % [0.0, 0.0]) | 9 (90.0 % [70.0, 100.0]) | 58.0 % [44.0, 72.0] | 0 | 4.483 [4.033, 4.983] |
| `ollama:kimi-k3` | grounded-docs (full-text) | 81.7 % [71.7, 91.7] | 42 | 8 | 3 | 7 | 0 | 0 | 0 (0.0 % [0.0, 0.0]) | 0 (0.0 % [0.0, 0.0]) | 7 (70.0 % [40.0, 100.0]) | 10.0 % [2.0, 18.0] | 0 | 3.45 [2.917, 4.05] |

## Tool errors

Tool calls the server refused or could not answer (an argument it does not take, a path the version lacks...), over the answered questions. Each costs the agent a turn, and the harness ends a run whose tool fails twice.

| Agent model | Arm | Runs with a tool error | Tool errors | By tool |
|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 1 of 60 | 2 | `search_docs` 2 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 4 of 60 | 4 | `read_page` 1, `search_docs` 3 |
| `ollama:kimi-k3` | exactdocs (bm25) | 1 of 60 | 1 | `read_article` 1 |
| `ollama:kimi-k3` | grounded-docs (full-text) | 14 of 60 | 23 | `find_version` 9, `read_page` 4, `search_docs` 10 |

## Cost per question

Each: mean [95% interval of the mean]; median; 95th percentile, over the questions without a provider failure. Wall time leaves out the time lost to provider retries.

| Agent model | Arm | Wall time (s) | Input tokens | Output tokens, thinking included | Thinking tokens | USD | Retried requests |
|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 2.9 [2.6, 3.2]; p50 2.7; p95 5.1 | 177 [176, 179]; p50 178; p95 184 | 745 [651, 842]; p50 696; p95 1,362 | 356 [307, 411]; p50 330; p95 646 (estimated) | unpriced | 0 |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 5.0 [4.4, 5.8]; p50 4.2; p95 9.7 | 50,381 [34,420, 72,490]; p50 28,027; p95 143,133 | 824 [726, 945]; p50 724; p95 1,758 | 467 [404, 548]; p50 384; p95 834 (estimated) | unpriced | 0 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 4.2 [3.6, 5.0]; p50 3.4; p95 8.7 | 41,413 [24,766, 64,716]; p50 13,677; p95 177,336 | 784 [680, 901]; p50 703; p95 1,415 | 358 [301, 429]; p50 318; p95 725 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | none | 19.1 [13.8, 25.9]; p50 9.8; p95 56.1 | 255 [254, 257]; p50 256; p95 263 | 1,913 [1,381, 2,584]; p50 966; p95 5,723 | 1,655 [1,132, 2,315]; p50 714; p95 5,443 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | exactdocs (bm25) | 13.3 [11.6, 15.2]; p50 10.2; p95 30.1 | 33,107 [28,356, 38,938]; p50 24,519; p95 62,474 | 1,186 [1,049, 1,346]; p50 965; p95 2,329 | 671 [566, 795]; p50 509; p95 1,646 (estimated) | unpriced | 0 |
| `ollama:kimi-k3` | grounded-docs (full-text) | 8.4 [7.2, 9.9]; p50 6.5; p95 19.2 | 16,065 [12,153, 20,731]; p50 8,685; p95 57,412 | 1,008 [866, 1,170]; p50 790; p95 2,596 | 560 [449, 688]; p50 383; p95 1,901 (estimated) | unpriced | 0 |

## Against the other arms, on the same cases

Each arm against `none` (and `exactdocs`), for the same agent model and the cases both answered without a provider failure: the difference (this arm minus the other), its paired bootstrap interval and the p-value; accuracy by McNemar's test (mid-p), time and tokens by a paired sign-flip permutation test. The ratio is this arm's mean over the other's. **Bold**: significant at 5%.

| Agent model | Arm | Against | Cases | Accuracy (points) | Gained / lost | Wall time (s) | Time ratio | Output tokens | Output ratio | Input tokens |
|---|---|---|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | none | 60 | **+26.7** [+15.0, +40.0]; p 7.6e-05 | 17 / 1 | **+2.1** [+1.5, +2.9]; p 0.0001 | 1.74x | +79 [-22, +187]; p 0.14 | 1.11x | **+50,204** [+34,243, +72,313]; p 0.0001 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | none | 60 | **+31.7** [+20.0, +43.3]; p 1.9e-06 | 19 / 0 | **+1.3** [+0.7, +2.0]; p 0.0001 | 1.45x | +38 [-46, +129]; p 0.39 | 1.05x | **+41,236** [+24,589, +64,538]; p 0.0001 |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | exactdocs (bm25) | 60 | +5.0 [-5.0, +16.7]; p 0.39 | 7 / 4 | **-0.8** [-1.4, -0.3]; p 0.003 | 0.84x | -41 [-132, +57]; p 0.4 | 0.95x | -8,968 [-20,714, +1,925]; p 0.13 |
| `ollama:kimi-k3` | exactdocs (bm25) | none | 60 | **+50.0** [+38.3, +63.3]; p 9.3e-10 | 30 / 0 | -5.8 [-12.6, -0.4]; p 0.067 | 0.7x | **-727** [-1,395, -193]; p 0.013 | 0.62x | **+32,851** [+28,102, +38,681]; p 0.0001 |
| `ollama:kimi-k3` | grounded-docs (full-text) | none | 60 | **+48.3** [+35.0, +61.7]; p 1.9e-09 | 29 / 0 | **-10.6** [-17.4, -5.4]; p 0.0001 | 0.44x | **-905** [-1,570, -375]; p 0.0005 | 0.53x | **+15,809** [+11,897, +20,476]; p 0.0001 |
| `ollama:kimi-k3` | grounded-docs (full-text) | exactdocs (bm25) | 60 | -1.7 [-11.7, +8.3]; p 0.77 | 5 / 6 | **-4.9** [-6.4, -3.5]; p 0.0001 | 0.64x | **-179** [-262, -95]; p 0.0003 | 0.85x | **-17,042** [-20,451, -14,073]; p 0.0001 |

In brackets: the 95% interval, a percentile bootstrap over the questions (10,000 resamples, seed 489); with a few dozen questions per kind or project, theirs are wide.

## Accuracy per kind

| Agent model | Arm | conceptual | cross-page | how-to | identifier-lookup | unanswerable | version-change |
|---|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 30.0 % [0.0, 60.0] (10) | 0.0 % [0.0, 0.0] (10) | 20.0 % [0.0, 50.0] (10) | 10.0 % [0.0, 30.0] (10) | 20.0 % [0.0, 50.0] (10) | 0.0 % [0.0, 0.0] (10) |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 60.0 % [30.0, 90.0] (10) | 30.0 % [0.0, 60.0] (10) | 50.0 % [20.0, 80.0] (10) | 30.0 % [0.0, 60.0] (10) | 50.0 % [20.0, 80.0] (10) | 20.0 % [0.0, 50.0] (10) |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 80.0 % [50.0, 100.0] (10) | 40.0 % [10.0, 70.0] (10) | 70.0 % [40.0, 90.2] (10) | 20.0 % [0.0, 50.0] (10) | 50.0 % [20.0, 80.0] (10) | 10.0 % [0.0, 30.0] (10) |
| `ollama:kimi-k3` | none | 70.0 % [40.0, 100.0] (10) | 20.0 % [0.0, 50.0] (10) | 40.0 % [10.0, 70.0] (10) | 30.0 % [0.0, 60.0] (10) | 20.0 % [0.0, 50.0] (10) | 20.0 % [0.0, 50.0] (10) |
| `ollama:kimi-k3` | exactdocs (bm25) | 90.0 % [70.0, 100.0] (10) | 80.0 % [50.0, 100.0] (10) | 90.0 % [70.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) | 90.0 % [70.0, 100.0] (10) | 80.0 % [50.0, 100.0] (10) |
| `ollama:kimi-k3` | grounded-docs (full-text) | 90.0 % [70.0, 100.0] (10) | 90.0 % [70.0, 100.0] (10) | 100.0 % [100.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) | 70.0 % [40.0, 100.0] (10) |

## Accuracy per project

| Agent model | Arm | electron | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|---|---|
| `ollama:gpt-oss:120b` | none | 16.7 % [0.0, 41.7] (12) | 25.0 % [0.0, 50.0] (12) | 8.3 % [0.0, 25.0] (12) | 8.3 % [0.0, 25.0] (12) | 8.3 % [0.0, 25.0] (12) |
| `ollama:gpt-oss:120b` | exactdocs (bm25) | 33.3 % [8.3, 58.3] (12) | 58.3 % [33.3, 83.3] (12) | 25.0 % [0.0, 50.0] (12) | 58.3 % [33.3, 83.3] (12) | 25.0 % [0.0, 50.0] (12) |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | 33.3 % [8.3, 58.3] (12) | 66.7 % [41.7, 91.7] (12) | 33.3 % [8.3, 58.3] (12) | 50.0 % [25.0, 75.0] (12) | 41.7 % [16.7, 66.7] (12) |
| `ollama:kimi-k3` | none | 25.0 % [0.0, 50.0] (12) | 25.0 % [0.0, 50.0] (12) | 41.7 % [16.7, 66.7] (12) | 33.3 % [8.3, 58.3] (12) | 41.7 % [16.7, 66.7] (12) |
| `ollama:kimi-k3` | exactdocs (bm25) | 66.7 % [41.7, 91.7] (12) | 83.3 % [58.3, 100.0] (12) | 66.7 % [41.7, 91.7] (12) | 100.0 % [100.0, 100.0] (12) | 100.0 % [100.0, 100.0] (12) |
| `ollama:kimi-k3` | grounded-docs (full-text) | 66.7 % [41.7, 91.7] (12) | 83.3 % [58.3, 100.0] (12) | 66.7 % [41.7, 91.7] (12) | 91.7 % [75.0, 100.0] (12) | 100.0 % [100.0, 100.0] (12) |

## Runs without an answer

2 runs: `no_answer` is the agent's (a miss, counted), `error` the provider's or the judge's (left out of every rate and test).

| Agent model | Arm | Case | Grade | Why |
|---|---|---|---|---|
| `ollama:gpt-oss:120b` | exactdocs (bm25) | starlette 1.10.0: If the first of several background tasks raises, do the others still run? | no_answer | no answer: UnexpectedModelBehavior: Tool 'search_docs' exceeded max retries count of 1. Consider raising the retry limit, or see the docs on tool retries: https |
| `ollama:gpt-oss:120b` | grounded-docs (full-text) | zod v4.0.17: How do I define a two-way schema so I can decode an ISO string into a Date and .encode() it back? | no_answer | no answer: UsageLimitExceeded: The next request would exceed the request_limit of 20. Consider raising the limit, or see the docs on usage limits for budget-awa |

## Documentation servers

- **exactdocs (bm25)**: server: exactdocs serve --stdio; version: 0.0.0.post140.dev0+eee1e310; tools: article_outline, list_articles, list_libraries, query-docs, read_article, read_chunk, resolve-library-id, search_all_docs, search_docs, view_article, view_search
- **grounded-docs (full-text)**: server: @arabold/docs-mcp-server 3.4.1 (read-only, HTTP); integrity: `sha512-IZQKYKs3p939Tt7N14JDLdukWzDmjOyp1QLARdpFZljh25eAT7cfY0Krtajg0UPpzJOIsHWpp0UBslioskmNzA==`; configuration: full-text: no embedding model: full-text search only, what it does when no provider credentials are set; indexed: 15 pinned versions, 6,263 chunks; node: v22.23.5; tools: find_version, list_libraries, list_pages, read_page, search_docs

## Retrieval configurations

- **bm25**: `EXACTDOCS_AI__MODE=bm25`; searches answered by bm25: 217
<!-- /bench -->

## What a run measures

Per agent model and arm:

- accuracy (correct, plus a refusal on an `unanswerable` case) overall, per question kind and per
  project;
- answers true only of another version;
- refusals on answerable cases, and correct refusals on `unanswerable` cases;
- how often the agent read every part of the answer in full (a section of each part, or one of
  its alternatives; for `grounded-docs`, a whole page; not measured for `context7`);
- tool calls, and the calls that failed (*Tool errors*);
- the cost per question: wall time, input tokens, output tokens with the thinking, thinking
  tokens on their own, USD.

Every rate and mean has a 95% interval, and every cost its median and 95th percentile.
Each arm is compared with `none` on the same cases, and `grounded-docs` (and `context7`) with
`exactdocs` too: McNemar's test for accuracy, a paired permutation test for time and tokens ([Method](method.md#agent-metrics-and-the-judge),
[Intervals and significance](method.md#intervals-and-significance)).

A question the provider failed on is an error, left out of every rate and test, never a wrong
answer.

## What produces the results

A run with real models, by hand:

- the manual workflow *Agent benchmark (real providers)*
  (`.github/workflows/agent-bench.yml`, `workflow_dispatch`, environment `eval-providers`), with
  the inputs `agent_models`, `judge_model`, `arms`, `thinking`, `retrieval` and `args`; its report
  is the artifact `agent-bench`;
- or locally, as above, with the providers' keys in the environment (the report never records
  one).

The recorded run is `packages/exactdocs/evals/results/agent.json` (and `agent.md`); `just
bench-pages` fills this page's tables from it. The flags, the keys the workflow reads and the
labelling rules are in [The agent benchmark](../evals/agent-bench.md).

!!! note "The stand-in run"
    `just agent-bench run --offline` uses scripted models to check the plumbing. Its numbers say
    nothing about an agent and are not published.
