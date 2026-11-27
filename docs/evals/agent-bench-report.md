# The agent benchmark's report

!!! abstract "TL;DR"
    - Each run writes `reports/evals/agent-bench.json` and a Markdown copy, with one cell per agent
      model and arm (and retrieval configuration).
    - Quality: accuracy, answers wrong for the version, refusals, and whether the agent read the
      sections a case names. Tool errors per arm. Cost per question: wall time, tokens, thinking,
      USD and retries.
    - Every rate and mean has a 95% bootstrap interval. Each arm is compared with `none`, and
      `context7` and `grounded-docs` with `exactdocs` too, on the same cases: McNemar's test for
      accuracy, a paired permutation test for time and tokens.
    - `meta` records what a rerun needs: models, arms, servers, versions and commits.

How the run itself works is on [The agent benchmark](agent-bench.md).

## The report

`reports/evals/agent-bench.json`, and `.md` next to it (also appended to `$GITHUB_STEP_SUMMARY`).

- One cell per agent model and arm (and configuration, for `exactdocs` and `grounded-docs`).
- Every rate and mean is over the questions without a provider failure (`answered`).

### Quality

- Grades and accuracy (share `correct`, plus `refused` on `unanswerable` cases), overall, per kind
  and per project.
- *No answer* and *Errors*.
- *Wrong for the version*: answers the judge flagged `wrong_version`, and their share.
- *Refused, answerable*: answerable questions the agent refused (misses).
- *Correct refusals, unanswerable*.
- *Read the answer*: of the answerable questions, the share where the agent read in full every
  part the case names, at its version: a section of each part, or one of its alternatives (#501).
    - Search snippets do not count.
    - A case's sections are, by construction, where its facts are stated, so this measures whether
      the cited text holds the required facts.
    - `n/a` for `none` and `context7` ([How a run works](agent-bench.md#how-a-run-works)).
- *Read another version*.
- Tool calls per question.

### Tool errors

Per arm with tools (#573):

- the runs with a tool call that failed: an argument the server refused, a path the version
  lacks... (`runs_with_tool_errors`);
- how many calls failed (`tool_errors`), and which tools (`tool_errors_by_tool`).

Each costs the agent a turn, and the harness ends a run whose tool fails twice (pydantic-ai's one
retry), so a tool's strictness shows up as `no_answer`.

### Cost per question

Each as mean with its 95% interval, p50 and p95 (nearest rank):

- wall time (retries left out);
- input tokens;
- output tokens with the thinking;
- thinking tokens on their own (marked *estimated*, or *not returned*);
- USD;
- the provider retries.

### Intervals and comparisons

- Every rate and mean has its 95% interval (`intervals`, a percentile bootstrap over the questions,
  as in [Intervals and paired tests](statistics.md#intervals-and-paired-tests)).
- **Against the other arms, on the same cases** (`versus`): each arm against `none`, and
  `context7` and `grounded-docs` against `exactdocs` too, for the same agent model and the cases
  both answered (a baseline arm's first configuration).
    - The accuracy difference, by McNemar's test (mid-p).
    - The wall time, output tokens and input tokens, by a paired sign-flip permutation test.
    - Each with its paired bootstrap interval, and the ratio of the means.
    - This answers "how much longer does the agent take with the tool, and is it worth it".
- **Against the first retrieval configuration**: for each retrieval configuration of an arm but
  its first, McNemar's test of its accuracy against the first one's (`reference`,
  `versus_reference`). Put the baseline first (`--retrieval`), e.g. BM25 when comparing models.
- *Runs without an answer*: the `no_answer` and `error` runs and why.
- *Documentation servers*: what each setup's server was (`meta.servers`).

### What a rerun needs

- `statistics` records the seed, resamples, confidence and level of the intervals and tests.
- `meta` holds what a rerun needs:
    - the agent models, the judge model, the arms and their instructions;
    - each `exactdocs` retrieval configuration's settings;
    - each arm's server (`servers`: release, integrity hash, configuration, the tools the agent
      got; empty with stand-in tools);
    - the selection of cases, the thinking setting, the limits and retries;
    - where the models are served (`providers`: base URLs only);
    - the ExactDocs version and the repository commit the run started from;
    - every imported version with its pinned and recorded commit;
    - how many answers were kept from an earlier run of the same command (`resumed`: those ran at
      that run's commit and time).
- `questions` holds every question's record: tool calls, chunks read as `<chunk ID>@<version>`,
  tokens, thinking, wall and retry time, USD, the answer as given, the judge's reason.

!!! info "No credential is recorded"
    - A retrieval setting whose name holds `KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `AUTH`, `HEADER`
      and the like is recorded as `<redacted>`.
    - Base URLs lose their user, password and query.
    - Error messages and the judge's reasons have every secret-named environment value and
      `Bearer <token>` replaced (`agent_bench/redact.py`).
    - The API keys are read from the environment only.
    - Each documentation server gets none of the agents' keys: ExactDocs only its own settings,
      Context7 only `CONTEXT7_API_KEY` (recorded as `CONTEXT7_API_KEY set`), Grounded Docs no
      credential.
