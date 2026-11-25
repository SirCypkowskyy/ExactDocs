## Harnesses

11 jobs (6 tasks; 5 golden questions; tasks pydantic-class-model-fields,query-gc-time-v5,starlette-startup-shutdown,starlette-template-response-v1,zod-error-messages-v4,zod-optional-unknown); models ollama:gpt-oss:120b, ollama:glm-5.3; arms none, exactdocs; up to 40 turns and 900 s a run. Isolation: a container per run (read-only root, no capabilities, CPU, memory and process limits) on an internal Docker network of its own; the only way out is the gate: the model provider's host through its proxy and the arm's MCP server through a forward.

| Harness | CLI | Released | Web tools | Turn limit, thinking |
|---|---|---|---|---|
| codex | `@openai/codex@0.171.0` | 2026-11-20 | off: web_search = "disabled" (Codex has no web fetch tool) | no turn limit (the wall limit); thinking: model_reasoning_effort |
| opencode | `opencode-ai@1.19.6` | 2026-11-17 | off: tools webfetch, websearch false; permission webfetch deny | agent build steps; thinking: the model's reasoningEffort (OpenAI-compatible) or --variant |

Thinking: `ollama:gpt-oss:120b` model default; `ollama:glm-5.3` model default.

### Coding tasks

| Harness / model / arm | Passed | Called the docs | Docs calls | Tool calls | Errors |
|---|---|---|---|---|---|
| codex / ollama:glm-5.3 / none | 100.0 % [100.0, 100.0] (n=6) | n/a | n/a | 8.8 [6.3, 11.7] | 0 |
| codex / ollama:glm-5.3 / exactdocs / bm25 | 100.0 % [100.0, 100.0] (n=6) | 100.0 % [100.0, 100.0] (n=6) | 5.5 [4.8, 6.3] | 11.3 [10.5, 12.2] | 0 |
| codex / ollama:gpt-oss:120b / none | 100.0 % [100.0, 100.0] (n=1) | n/a | n/a | 6.0 [6.0, 6.0] | 5 |
| codex / ollama:gpt-oss:120b / exactdocs / bm25 | 0.0 % [0.0, 0.0] (n=1) | 0.0 % [0.0, 0.0] (n=1) | 0.0 [0.0, 0.0] | 48.0 [48.0, 48.0] | 5 |
| opencode / ollama:glm-5.3 / none | 100.0 % [100.0, 100.0] (n=6) | n/a | n/a | 13.5 [11.5, 15.7] | 0 |
| opencode / ollama:glm-5.3 / exactdocs / bm25 | 100.0 % [100.0, 100.0] (n=6) | 100.0 % [100.0, 100.0] (n=6) | 5.7 [4.7, 6.7] | 13.8 [10.3, 17.0] | 0 |
| opencode / ollama:gpt-oss:120b / none | 66.7 % [33.3, 100.0] (n=6) | n/a | n/a | 9.5 [5.5, 16.7] | 0 |
| opencode / ollama:gpt-oss:120b / exactdocs / bm25 | 83.3 % [50.0, 100.0] (n=6) | 100.0 % [100.0, 100.0] (n=6) | 2.7 [2.3, 3.0] | 10.2 [7.8, 13.5] | 0 |

#### Coding tasks: cost per run

| Harness / model / arm | Wall time (s) | Input tokens | Output tokens (with thinking) | Thinking tokens | USD |
|---|---|---|---|---|---|
| codex / ollama:glm-5.3 / none | 28.0 [16.0, 41.5]; p50 15.8; p95 53.9 | 139,238 [85,908, 197,888] | 3,676 [1,758, 5,953] | not reported | unpriced |
| codex / ollama:glm-5.3 / exactdocs / bm25 | 18.8 [15.1, 23.1]; p50 16.0; p95 27.7 | 168,497 [146,681, 194,140] | 2,195 [1,631, 2,786] | not reported | unpriced |
| codex / ollama:gpt-oss:120b / none | 40.4 [40.4, 40.4]; p50 40.4; p95 40.4 | 48,832 [48,832, 48,832] | 2,507 [2,507, 2,507] | not reported | unpriced |
| codex / ollama:gpt-oss:120b / exactdocs / bm25 | 156.5 [156.5, 156.5]; p50 156.5; p95 156.5 | 994,655 [994,655, 994,655] | 16,070 [16,070, 16,070] | not reported | unpriced |
| opencode / ollama:glm-5.3 / none | 41.3 [26.3, 60.1]; p50 30.1; p95 85.6 | 127,212 [89,399, 168,659] | 3,953 [2,028, 6,610] | not reported | unpriced |
| opencode / ollama:glm-5.3 / exactdocs / bm25 | 33.3 [26.0, 41.0]; p50 32.6; p95 48.3 | 219,702 [150,492, 285,930] | 3,022 [2,098, 3,820] | not reported | unpriced |
| opencode / ollama:gpt-oss:120b / none | 20.9 [14.4, 30.1]; p50 14.4; p95 43.0 | 92,313 [44,160, 181,490] | 1,833 [848, 3,479] | not reported | unpriced |
| opencode / ollama:gpt-oss:120b / exactdocs / bm25 | 26.7 [15.1, 46.7]; p50 17.1; p95 75.4 | 125,014 [93,251, 168,100] | 1,551 [1,091, 2,244] | not reported | unpriced |

#### Coding tasks: against the harness's own `none` arm, on the same jobs

| Harness / model / arm | Jobs | Passed (pts [CI]; gained/lost; McNemar p) | Wall time (s [CI]; p; ratio) | Output tokens ([CI]; p; ratio) |
|---|---|---|---|---|
| codex / ollama:glm-5.3 / exactdocs / bm25 | 6 | +0.0 pts [+0.0, +0.0]; 0/0; p 1.0 | -9.1 [-22.7, +3.2]; p 0.2458; x0.67 | -1,481.0 [-3,693.0, +345.8]; p 0.2458; x0.6 |
| opencode / ollama:glm-5.3 / exactdocs / bm25 | 6 | +0.0 pts [+0.0, +0.0]; 0/0; p 1.0 | -7.9 [-26.5, +7.7]; p 0.5243; x0.81 | -931.2 [-3,091.5, +692.5]; p 0.5574; x0.76 |
| opencode / ollama:gpt-oss:120b / exactdocs / bm25 | 6 | +16.7 pts [+0.0, +50.0]; 1/0; p 0.5 | +5.8 [-0.7, +16.7]; p 0.3734; x1.28 | -281.7 [-1,268.0, +393.2]; p 0.8463; x0.85 |

#### Coding tasks: against the same model and arm without a harness, on the same jobs

| Harness / model / arm | Jobs | Passed (pts [CI]; gained/lost; McNemar p) | Wall time (s [CI]; p; ratio) | Output tokens ([CI]; p; ratio) |
|---|---|---|---|---|
| codex / ollama:gpt-oss:120b / none | 1 | +100.0 pts [+100.0, +100.0]; 1/0; p 0.5 | +32.4 [+32.4, +32.4]; p 1.0; x5.06 | +1,643.0 [+1,643.0, +1,643.0]; p 1.0; x2.9 |
| codex / ollama:gpt-oss:120b / exactdocs / bm25 | 1 | +0.0 pts [+0.0, +0.0]; 0/0; p 1.0 | +139.5 [+139.5, +139.5]; p 1.0; x9.17 | +13,729.0 [+13,729.0, +13,729.0]; p 1.0; x6.86 |
| opencode / ollama:gpt-oss:120b / none | 6 | +33.3 pts [+0.0, +66.7]; 2/0; p 0.25 | +11.4 [+8.1, +15.1]; p 0.0297; x2.2 | +358.5 [+118.0, +621.8]; p 0.06319; x1.24 |
| opencode / ollama:gpt-oss:120b / exactdocs / bm25 | 6 | +16.7 pts [+0.0, +50.0]; 1/0; p 0.5 | +16.2 [+5.4, +33.3]; p 0.0297; x2.54 | +323.8 [+129.8, +560.0]; p 0.0297; x1.26 |

### Golden questions

| Harness / model / arm | Accurate | Called the docs | Docs calls | Tool calls | Errors |
|---|---|---|---|---|---|
| opencode / ollama:gpt-oss:120b / none | 20.0 % [0.0, 60.0] (n=5) | n/a | n/a | 0.0 [0.0, 0.0] | 0 |
| opencode / ollama:gpt-oss:120b / exactdocs / bm25 | 60.0 % [20.0, 100.0] (n=5) | 100.0 % [100.0, 100.0] (n=5) | 3.4 [2.2, 4.8] | 3.8 [2.2, 5.4] | 0 |

#### Golden questions: cost per run

| Harness / model / arm | Wall time (s) | Input tokens | Output tokens (with thinking) | Thinking tokens | USD |
|---|---|---|---|---|---|
| opencode / ollama:gpt-oss:120b / none | 5.6 [5.5, 5.9]; p50 5.5; p95 6.1 | 6,118 [6,116, 6,121] | 316 [281, 352] | not reported | unpriced |
| opencode / ollama:gpt-oss:120b / exactdocs / bm25 | 8.7 [7.6, 9.8]; p50 8.7; p95 10.3 | 54,739 [30,976, 78,503] | 686 [526, 841] | not reported | unpriced |

#### Golden questions: against the harness's own `none` arm, on the same jobs

| Harness / model / arm | Jobs | Accurate (pts [CI]; gained/lost; McNemar p) | Wall time (s [CI]; p; ratio) | Output tokens ([CI]; p; ratio) |
|---|---|---|---|---|
| opencode / ollama:gpt-oss:120b / exactdocs / bm25 | 5 | +40.0 pts [+0.0, +80.0]; 2/0; p 0.25 | +3.1 [+1.8, +4.3]; p 0.05929; x1.55 | +370.0 [+216.6, +506.6]; p 0.05929; x2.17 |

### Network

| Harness | Built-in web calls | Hosts the gate refused |
|---|---|---|
| codex | 0 | `api.github.com:443` (24), `chatgpt.com:443` (24) |
| opencode | 0 | `registry.npmjs.org:443` (34) |

### Runs without an answer

- codex / ollama:gpt-oss:120b / exactdocs / pydantic-class-model-fields: provider: igh demand, which may cause temporary errors.); We’re currently experiencing high demand, which may cause temporary errors.; We’re currently experiencing high demand, which may cause temporary errors.
- codex / ollama:gpt-oss:120b / none / starlette-startup-shutdown: provider: igh demand, which may cause temporary errors.); We’re currently experiencing high demand, which may cause temporary errors.; We’re currently experiencing high demand, which may cause temporary errors.
- codex / ollama:gpt-oss:120b / none / starlette-template-response-v1: provider: igh demand, which may cause temporary errors.); We’re currently experiencing high demand, which may cause temporary errors.; We’re currently experiencing high demand, which may cause temporary errors.
- codex / ollama:gpt-oss:120b / exactdocs / starlette-template-response-v1: provider: igh demand, which may cause temporary errors.); We’re currently experiencing high demand, which may cause temporary errors.; We’re currently experiencing high demand, which may cause temporary errors.
- codex / ollama:gpt-oss:120b / none / query-gc-time-v5: provider: igh demand, which may cause temporary errors.); We’re currently experiencing high demand, which may cause temporary errors.; We’re currently experiencing high demand, which may cause temporary errors.
- codex / ollama:gpt-oss:120b / exactdocs / query-gc-time-v5: provider: igh demand, which may cause temporary errors.); We’re currently experiencing high demand, which may cause temporary errors.; We’re currently experiencing high demand, which may cause temporary errors.
- codex / ollama:gpt-oss:120b / none / zod-error-messages-v4: provider: igh demand, which may cause temporary errors.); We’re currently experiencing high demand, which may cause temporary errors.; We’re currently experiencing high demand, which may cause temporary errors.
- codex / ollama:gpt-oss:120b / exactdocs / zod-error-messages-v4: provider: igh demand, which may cause temporary errors.); We’re currently experiencing high demand, which may cause temporary errors.; We’re currently experiencing high demand, which may cause temporary errors.
- codex / ollama:gpt-oss:120b / none / zod-optional-unknown: provider: igh demand, which may cause temporary errors.); We’re currently experiencing high demand, which may cause temporary errors.; We’re currently experiencing high demand, which may cause temporary errors.
- codex / ollama:gpt-oss:120b / exactdocs / zod-optional-unknown: provider: igh demand, which may cause temporary errors.); We’re currently experiencing high demand, which may cause temporary errors.; We’re currently experiencing high demand, which may cause temporary errors.

### Every task

| Job | codex / ollama:glm-5.3 / none | codex / ollama:glm-5.3 / exactdocs / bm25 | codex / ollama:gpt-oss:120b / none | codex / ollama:gpt-oss:120b / exactdocs / bm25 | opencode / ollama:glm-5.3 / none | opencode / ollama:glm-5.3 / exactdocs / bm25 | opencode / ollama:gpt-oss:120b / none | opencode / ollama:gpt-oss:120b / exactdocs / bm25 |
|---|---|---|---|---|---|---|---|---|
| pydantic-class-model-fields | pass | pass, 5 docs | pass | error, 0 docs | pass | pass, 6 docs | pass | pass, 3 docs |
| query-gc-time-v5 | pass | pass, 5 docs | error | error, 4 docs | pass | pass, 4 docs | pass | pass, 2 docs |
| starlette-startup-shutdown | pass | pass, 4 docs | error | failed, 0 docs | pass | pass, 6 docs | pass | pass, 3 docs |
| starlette-template-response-v1 | pass | pass, 6 docs | error | error, 4 docs | pass | pass, 7 docs | failed (TemplateResponse(name, context)) | failed, 3 docs |
| zod-error-messages-v4 | pass | pass, 7 docs | error | error, 0 docs | pass | pass, 4 docs | failed (required_error / invalid_type_error / errorMap) | pass, 3 docs |
| zod-optional-unknown | pass | pass, 6 docs | error | error, 1 docs | pass | pass, 7 docs | pass | pass, 2 docs |

### Every question

| Job | opencode / ollama:gpt-oss:120b / none | opencode / ollama:gpt-oss:120b / exactdocs / bm25 |
|---|---|---|
| electron v45.3.2: How do I send a one-way message from a renderer to the main process? | partially_correct | pass, 2 docs |
| pydantic v2.14.3: How do I add a check that runs after Pydantic has validated a field? | pass | pass, 6 docs |
| starlette 1.10.0: How do I run code when the application starts up and when it shuts down? | wrong | pass, 3 docs |
| tanstack-query v5.90.3: How do I refresh the todos list after a mutation succeeds? | partially_correct | partially_correct, 4 docs |
| zod v4.6.7: How do I turn a string input into a number before validating it? | partially_correct | partially_correct, 2 docs |
