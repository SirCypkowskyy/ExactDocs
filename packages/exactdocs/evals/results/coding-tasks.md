## Coding tasks

6 tasks (tasks starlette-startup-shutdown,starlette-template-response-v1,zod-error-messages-v4,zod-optional-unknown,pydantic-class-model-fields,query-gc-time-v5); arms none, exactdocs; agent models ollama:gpt-oss:120b; up to 20 requests a task; thinking model default; cutoff 2024-06-30. Sandbox: docker, network none: --network none.

| Model / arm | Passed | After the cutoff | Forbidden API used | Files changed | Errors |
|---|---|---|---|---|---|
| ollama:gpt-oss:120b / none | 33.3 % [0.0, 66.7] (n=6) | 33.3 % [0.0, 66.7] (n=6) | 50.0 % [16.7, 83.3] (n=6) | 1.0 [1.0, 1.0]; p50 1.0; p95 1.0 | 0 |
| ollama:gpt-oss:120b / exactdocs / bm25 | 66.7 % [33.3, 100.0] (n=6) | 66.7 % [33.3, 100.0] (n=6) | 16.7 % [0.0, 50.0] (n=6) | 1.0 [1.0, 1.0]; p50 1.0; p95 1.0 | 0 |

### Passed, per project

| Model / arm | pydantic | starlette | tanstack-query | zod |
|---|---|---|---|---|
| ollama:gpt-oss:120b / none | 0.0 % [0.0, 0.0] (n=1) | 0.0 % [0.0, 0.0] (n=2) | 100.0 % [100.0, 100.0] (n=1) | 50.0 % [0.0, 100.0] (n=2) |
| ollama:gpt-oss:120b / exactdocs / bm25 | 100.0 % [100.0, 100.0] (n=1) | 0.0 % [0.0, 0.0] (n=2) | 100.0 % [100.0, 100.0] (n=1) | 100.0 % [100.0, 100.0] (n=2) |

### Cost per task

| Model / arm | Wall time (s) | Input tokens | Output tokens | Tool calls | Docs calls | USD |
|---|---|---|---|---|---|---|
| ollama:gpt-oss:120b / none | 9.5 [6.2, 15.3]; p50 6.6; p95 24.0 | 21,842 [6,146, 44,261]; p50 6,419; p95 74,051 | 1,474 [699, 2,902]; p50 812; p95 5,007 | 8.5 [5.7, 12.8]; p50 6.0; p95 19.0 | 0.0 [0.0, 0.0]; p50 0.0; p95 0.0 | unpriced |
| ollama:gpt-oss:120b / exactdocs / bm25 | 10.5 [8.2, 13.4]; p50 9.4; p95 17.1 | 44,655 [32,858, 57,397]; p50 32,788; p95 68,322 | 1,227 [885, 1,707]; p50 888; p95 2,341 | 9.3 [7.5, 11.8]; p50 8.0; p95 15.0 | 2.0 [0.5, 3.8]; p50 1.0; p95 6.0 | unpriced |

### Against `none`, on the same tasks (McNemar, mid-p)

| Model / arm | Tasks | Difference [95% CI] | Gained / lost | p | Significant |
|---|---|---|---|---|---|
| ollama:gpt-oss:120b / exactdocs / bm25 | 6 | +33.3 pts [+0.0, +66.7] | 2 / 0 | 0.25 | no |

### Forbidden APIs used

- ollama:gpt-oss:120b / none: TemplateResponse(name, context) (1), model_fields on an instance (1), required_error / invalid_type_error / errorMap (1)
- ollama:gpt-oss:120b / exactdocs / bm25: TemplateResponse(name, context) (1)

### Every task

| Task | ollama:gpt-oss:120b / none | ollama:gpt-oss:120b / exactdocs / bm25 |
|---|---|---|
| pydantic-class-model-fields | fail (model_fields on an instance) | pass |
| query-gc-time-v5 | pass | pass |
| starlette-startup-shutdown | fail | fail |
| starlette-template-response-v1 | fail (TemplateResponse(name, context)) | fail (TemplateResponse(name, context)) |
| zod-error-messages-v4 | fail (required_error / invalid_type_error / errorMap) | pass |
| zod-optional-unknown | pass | pass |
