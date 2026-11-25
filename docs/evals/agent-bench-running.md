# Running the agent benchmark

!!! abstract "TL;DR"
    - `just agent-bench run --offline` runs the whole benchmark on stand-in models with no
      provider. It proves the plumbing, not quality.
    - Real runs take pydantic-ai model names for the agents and the judge, and `--resume` after a
      provider failure. Use a judge from another vendor than the agents where you can.
    - The manual *Agent benchmark (real providers)* workflow runs the same command.
    - The judge is checked against people: at least 50 answers labelled by hand, blind like the
      judge.

## Running it

```bash
just agent-bench run --offline --projects starlette,zod --limit 4   # stand-ins, no provider
OLLAMA_BASE_URL=https://ollama.com/v1 OLLAMA_API_KEY=... just agent-bench run \
  --agent-model ollama:gpt-oss:120b --agent-model ollama:kimi-k3 --judge-model ollama:glm-5.3 \
  --arm none,exactdocs --retrieval bm25:mode=bm25 --thinking medium \
  --per-stratum 3 --concurrency 3            # 90 cases: 3 per kind and project
just agent-bench run ... --resume            # ask again what failed on the provider's side
just agent-bench run --help
```

### Models

`--agent-model` (repeat for several) and `--judge-model` are
[pydantic-ai model names](https://ai.pydantic.dev/models/overview/) (`<provider>:<model>`).

- The provider's usual variables give the key: `OPENAI_API_KEY`, `OPENAI_BASE_URL` for a gateway,
  `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`.
- `ollama:<model>` is an Ollama model through pydantic-ai's Ollama provider at `OLLAMA_BASE_URL`
  (`https://ollama.com/v1` for Ollama Cloud) with `OLLAMA_API_KEY`, retried and measured as in
  [Retries](agent-bench.md#retries).
- Use a judge from another vendor than the agents where you can.

### Options

| Option | What it does |
|---|---|
| `--arm` | picks the arms (repeat or comma-separate; default `none,exactdocs`) |
| `--thinking on\|off\|minimal\|low\|medium\|high\|xhigh\|max` | sets the agents' thinking ([below](#thinking)) |
| `--retrieval name[:key=value,...]` | names one configuration of the `exactdocs` arm (repeat for several; [below](#retrieval-configurations)) |
| `--projects`, `--kinds`, `--limit N` | pick the cases (`--limit`: cases per project) |
| `--per-stratum N` (with `--seed`, default 495) | a stratified random sample of N cases per kind and project, as the golden set's review does |
| `--concurrency` | asks several questions at once (wall time then includes contention) |
| `--work-dir` | keeps the data directories and each server's log (`server-<configuration>.log`) |
| `--resume` | continues from `<report>.rows.jsonl` |
| `--offline` | uses the stand-ins ([below](#stand-ins)) |

#### Thinking

`--thinking` is pydantic-ai's `thinking`, sent to Ollama as `reasoning_effort`.

- Left out, each model keeps its default.
- The setting is recorded (`meta.thinking`); some models think whatever it says.

#### Retrieval configurations

- Each key of `--retrieval` is an ExactDocs AI setting path set as `EXACTDOCS_AI__<KEY>`:
    - `mode=hybrid` is `EXACTDOCS_AI__MODE=hybrid`;
    - `embedding.model=eval:...` is `EXACTDOCS_AI__EMBEDDING__MODEL`.
- It applies on top of the environment, for both the import and the server.
- Profiles (`eval:` above) come from the environment as for any instance
  (`EXACTDOCS_AI__PROVIDERS__EVAL__...`).
- The default is `bm25:mode=bm25` and `hybrid:mode=hybrid`. Without an embedding model the second
  falls back to BM25, which the report shows.

#### Stand-ins

`--offline` uses the stand-ins in `agent_bench/offline.py` (pydantic-ai `FunctionModel`s):

| Stand-in | What it does |
|---|---|
| `offline:search` | answers from the search snippets |
| `offline:read` | reads the top section first |
| `offline:think` | also returns thinking |
| with no tools (`none`) | each says it does not know |
| the judge | grades by word overlap with the facts |

They prove the plumbing, not quality.

### The manual workflow

The manual workflow *Agent benchmark (real providers)* (`.github/workflows/agent-bench.yml`,
`workflow_dispatch` only, environment `eval-providers`) runs the same command. The report is
uploaded as the artifact `agent-bench`.

| Input | What it is |
|---|---|
| `agent_models` | comma-separated |
| `judge_model` | |
| `arms` | default `none,exactdocs` |
| `thinking` | |
| `retrieval` | configurations separated by spaces |
| `args` | e.g. `--per-stratum 3` |

Keys:

- for the agents and the judge: the secrets `AGENT_BENCH_OPENAI_API_KEY`,
  `AGENT_BENCH_ANTHROPIC_API_KEY`, `AGENT_BENCH_GOOGLE_API_KEY`, `AGENT_BENCH_OLLAMA_API_KEY`, and
  the variables `AGENT_BENCH_OPENAI_BASE_URL` (for an OpenAI-compatible gateway) and
  `AGENT_BENCH_OLLAMA_BASE_URL`;
- for the server's models: the `eval` profile of the retrieval workflow (`EVAL_PROVIDER_*`).

## Judge agreement

The judge is checked against people: at least 50 answers labelled by hand, and the share where the
judge gave the same grade.

```bash
just agent-bench sample --report reports/evals/agent-bench.json --size 50   # -> agent-bench-labels.yaml
# fill in `grade` and `wrong_version` (true/false) for each answer
just agent-bench agreement --report reports/evals/agent-bench.json --labels reports/evals/agent-bench-labels.yaml
```

`sample` picks judged answers reproducibly (`--seed`) and writes each with its question, version,
kind, reference and facts, and blank labels.

The labeller is as blind as the judge:

- the answer is shown as the judge read it (names `[redacted]`);
- its ID is a hash that names neither the model nor the arm;
- the judge's grade is left out, so it cannot steer the labeller.

Label with the judge's grades, which the file's header repeats:

| Label | The answer |
|---|---|
| `correct` | states every fact, nothing the reference contradicts |
| `partially_correct` | states some of the facts, nothing contradicted |
| `wrong` | states none, contradicts the reference, or invents an API or behaviour |
| `refused` | says the documentation does not cover it or that it does not know (or declines) and states no facts |

For an `unanswerable` case, an answer saying the documentation does not cover it is labelled
`refused`, not `correct` (the report counts it as right for that kind); answering anyway is
`wrong`.

`agreement` prints:

- how many answers were labelled;
- how many the judge graded the same (`rate`);
- the same for `wrong_version`;
- a confusion table (hand grade to judge grades).

Entries left blank are skipped. Label answers from a real-model run: the stand-ins' answers are
not worth labelling.

## Tests

`tests/evals/test_agent_bench.py` and `tests/evals/test_agent_arms.py` run in CI. They cover:

- the recording, grounding and pricing;
- the arms and their instructions, and the blind judge;
- thinking tokens (reported, estimated, not returned);
- whose side a failure is on, and the retry log;
- the redaction of secrets;
- the report and its paired comparisons;
- the checkpoint and `--resume`, and agreement.

Both arms run end to end there with the stand-in models and the stand-in documentation tools of
`tests/fixtures/agent_bench_stand_ins.py` (an in-process MCP server), as do the scenarios of
`features/agent_bench.feature`.

The end-to-end test, marked `eval` (`uv run pytest -m eval`):

1. imports a two-version corpus built in a temporary repository;
2. starts `exactdocs serve --stdio` on it under two configurations;
3. runs every stand-in agent with both arms, and the stand-in judge, through it.
