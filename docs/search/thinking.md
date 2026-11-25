# Thinking level

!!! abstract "TL;DR"

    - `thinking` sets how much the `llm` and `judge` models think: `minimal`, `low`, `medium`, `high` or `xhigh`.
    - Unset, calls use the provider's default.
    - It is sent as each provider's own control, and set in the environment, over REST, or per library.

Current chat models think before they answer, and their thinking tokens are billed as output.
Several providers default to a high level (Gemini 4 Hydrogen and Neon default to `high`), while
the `llm` and `judge` roles do short, bounded work: a hypothetical answer, a list of ratings, a
few tool calls. `thinking` lowers (or raises) how much they think:

```toml
[ai.llm]
model = "gcp:gemini-4-hydrogen"
thinking = "low"          # EXACTDOCS_AI__LLM__THINKING: minimal, low, medium, high or xhigh

[ai.judge]
thinking = "minimal"      # EXACTDOCS_AI__JUDGE__THINKING; the judge is the LLM here
```

Unset, calls are made as before, at the provider's default. A judge that is the `llm` role thinks
as the `llm` does unless it has a level of its own. The level is sent as each provider's own
control, through pydantic-ai's model settings:

| Provider kind | What is sent |
|---|---|
| `google-vertex`, `google` (Gemini 3 and later) | `thinking_config.thinking_level` (`MINIMAL`, `LOW`, `MEDIUM`, `HIGH`; a level the model lacks snaps to the nearest, e.g. `minimal` to `LOW` on Gemini 3.1 Pro) |
| `google-vertex`, `google` (Gemini 2.5) | `thinking_config.thinking_budget`: 128, 2,048, 8,192 or 24,576 tokens |
| `anthropic` (adaptive thinking: Claude Opus and Sonnet 4.6 and later, Haiku 5.5) | `thinking: {type: adaptive}` with `output_config.effort` |
| `anthropic` (older Claude models) | `thinking.budget_tokens`: 1,024, 2,048, 10,000, 16,384 or 32,768; the budget is added to the answer's own token cap, which it counts toward |
| `openai` (Responses API), `azure` | `reasoning.effort` / `reasoning_effort` |
| `openrouter` | `reasoning.effort` |
| `openai-compatible`, `ollama`, `vllm`, `litellm` and the other OpenAI-API kinds | `reasoning_effort` |

Behind an OpenAI-compatible endpoint (a gateway's alias, an Azure deployment) a model is sent
`reasoning_effort` even when pydantic-ai does not know it: the endpoint takes the field, and only a
call tells whether the model does. Anthropic, Google and OpenAI's own API serve models
pydantic-ai knows; one that takes no thinking setting (`gemini-2.0-flash`, `gpt-4.1`) is refused a
level when it is saved over the REST API or in the UI (422 `thinking_unsupported`, naming the role
and the model). A level from the environment or the file that the model cannot take is logged as a
warning at start, shown on the *AI* page, and left out of every call.

Where it is set:

- the environment or the TOML file (above), read-only elsewhere;
- otherwise `PUT /api/v1/ai/roles/{llm|judge}` with `{"thinking": "low"}` (`null` clears it), or
  the *AI* page; `GET /api/v1/ai/roles` shows each role's `thinking`, its `own_thinking`, whether it
  is `thinking_configured`, and `thinking_unsupported` when its model cannot take it;
- for one library, `llm_thinking` and `judge_thinking` in its retrieval settings (below), which win
  over the instance's level, for its own model or the instance's.

Every call of the role uses the level: HyDE, the judge, the agentic mode and `exactdocs ai check`,
so the check's latency reflects it. Spend is counted as before, from the usage each provider
reports: thinking tokens are part of the output tokens.
