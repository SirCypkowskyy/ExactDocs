# Image budgets and retention

!!! abstract "TL;DR"
    - The wheel and the base image hold no models and no ML libraries (RUN-02). AI retrieval comes
      in two more image variants, `-ai` and `-local`, built from the same `deploy/Dockerfile`.
    - Budgets: wheel 5 MB, `base` 410 MB, `ai` 560 MB, `local` 950 MB. The base image is at
      404.1 MB on arm64, about 1.5% under its budget.
    - arm64 images come out larger than amd64 ones, so arm64 is the one that gets close to a
      budget. Pull request CI does not check it: a release or a dry run does.
    - Raising a budget needs a reason in the PR; dropping a dependency to stay inside it is the
      first choice.
    - The registry keeps the 5 newest dev and 10 newest stable images of each variant. PyPI
      releases are never deleted.

## Image retention

`.github/workflows/ghcr-retention.yml` keeps the registry small:

- the **5 newest dev images** (`X.Y.Z.devN`) and the **10 newest stable images** (`X.Y.Z`) of each
  variant;
- the variants (base, `-ai`, `-local`) are counted separately, so a release's three images do not
  push out another variant's older ones;
- a multi-arch image is removed with its platform images, cosign signature and attestations;
- untagged leftovers are deleted once they are a day old. A running release pushes its platform
  images untagged and tags them a few minutes later, so younger ones are left alone.

It runs after every successful tag release, weekly, and on demand:

```bash
gh workflow run ghcr-retention.yml -f dry-run=true   # shows what would be deleted
```

- Change `KEEP_DEV` / `KEEP_STABLE` in the workflow to adjust.
- PyPI releases are never deleted.

## Size and model-free budgets

RUN-02: many installs only ever use BM25, so the wheel and the base image hold no models and no ML
libraries. Operators who want AI retrieval should not have to build their own image, so the image
comes in three variants, the build targets of one `deploy/Dockerfile` (#246; decision record
[*Image variants*](../decisions/ai-retrieval.md#image-variants)).

CI enforces each budget with `deploy/check_artifacts.py`, in:

- the integration jobs *Docker image* and *Docker image variants*, which run when started by hand;
- the release's *Scan image* jobs.

The sizes land in the job summary.

!!! warning "Where the numbers come from"
    - Since #468 the CI jobs run on GitHub-hosted `ubuntu-24.04` (amd64), where the images come out
      smaller than on arm64 (353.0 MB against 387.1 MB for `base` before MCP Apps). So the arm64
      figures below come from the release's builds and earlier CI runs.
    - Since #478 the release checks both architectures, each natively on a hosted runner of its
      own ([CI/CD and runners](runners.md)).
    - arm64 is the one that gets close to a budget, and a pull request that adds a dependency only
      finds out in the release (or a [dry run](release-workflow.md#dry-run)).

| Artifact | Budget | Now (arm64) | Now (amd64) |
|---|---|---|---|
| wheel (with the UI) | 5 MB | 0.9 MB (CI, PR #237) | |
| image `base` (`<v>`) | 410 MB | 404.1 MB (CI, PR #464)<br/>387.1 MB before MCP Apps (PR #285) | 353.0 MB |
| image `ai` (`<v>-ai`: `exactdocs[ai]`) | 560 MB | 520.4 MB (CI, PR #285: +133 MB) | 492.0 MB |
| image `local` (`<v>-local`: `exactdocs[ai,local]` + default models) | 950 MB | 866.5 MB (CI, PR #285: +479 MB, of which 159 MB are the models) | 847.9 MB |

An image's size is its unpacked file bytes, `du -sxb /` in the container, which does not depend on
the image store.

### What else is checked

**wheel**

- no `*.safetensors`, `*.bin`, `*.onnx`, `*.gguf`, `*.pt`;
- no ML package in `Requires-Dist`.

**`base`**

- no such model file anywhere in the filesystem;
- no `ML_PACKAGES` distribution installed;
- no aiohttp.

**`ai`**

- as `base`, except that pydantic-ai(-slim) is allowed: it calls models over HTTP and runs none.

**`local`**

- of `ML_PACKAGES`, only fastembed, onnxruntime, tokenizers, huggingface-hub and pydantic-ai(-slim)
  (no torch, transformers, onnx, ...);
- both default models at their pinned revisions in `/opt/exactdocs/models` (the server's own
  marker check), with:
    - the pinned sha256 of their ONNX files (`MODEL_SHA256`);
    - their license `NOTICE`;
    - a directory UID 10001 cannot write;
    - `EXACTDOCS_MODELS_DIR` set to it;
- model files nowhere else (but ONNX Runtime's own few-KB examples);
- no aiohttp.

### Why these budgets

- The decision record estimated 531 MB for `-ai` and 887 MB for `-local` from the extras'
  site-packages (measured 2026-11-07 on x86_64) and set 560 MB and 950 MB.
- CI (arm64, PR #285, with Pillow 13) measured 387.1, 520.4 and 866.5 MB (387.0, 520.2 and
  867.6 MB with Pillow 12.3).
    - That is 7.1 % of headroom for `-ai`, the same margin as the base image's.
    - `-local` keeps 950 MB, 8.8 % of headroom (930 MB would be about 7 %), on purpose. It is the
      decision record's figure, and the extra 20 MB is room for a default-model update: a newer
      revision or a slightly larger cross-encoder replaces 159 MB of weights, which no dependency
      trimming can offset.
- amd64 images are 20 to 34 MB smaller than arm64 ones (353.0, 492.0 and 847.9 MB), so CI's arm64
  numbers are the ones that count.

Raising a budget needs a reason in the PR; dropping a dependency to stay inside it is the first
choice.

### Rules per variant

**Only `-local` may hold ONNX Runtime and model files.**

- The `-ai` image is checked against `ML_PACKAGES` like the base one, minus `pydantic-ai` and
  `pydantic-ai-slim` (`LLM_CLIENT_PACKAGES`).
- `-local` also allows what `[local]` brings (`LOCAL_PACKAGES`: fastembed, onnxruntime, tokenizers,
  huggingface-hub) and nothing else of the list.
- No variant holds **aiohttp**: Entra ID uses `azure.identity`'s sync token provider (#241), never
  `azure.identity.aio`.

**The `-local` models are baked in, not pulled at first start.** The image must work with
`--network none`, so:

1. The build runs `exactdocs models pull`, which fetches each default model at its pinned Hub
   revision (`PINNED_MODEL_REVISIONS`):
    - into a BuildKit cache mount (a rebuild contacts no Hub);
    - natively on the build platform (the files are the same for amd64 and arm64, and a
      cross-build pulls them natively too).
2. It copies the two folders into the image, owned by root and read-only.
3. The check compares their ONNX files with the sha256 the Hub records for them at the pinned
   revisions (`MODEL_SHA256` in `deploy/check_artifacts.py`; update it with
   `PINNED_MODEL_REVISIONS`). So a build is verified byte for byte, not only by the Hub commit and
   TLS.

`EXACTDOCS_MODELS_DIR=/opt/exactdocs/models` is set in the image. A model of your own goes into
another directory (a volume) with `exactdocs models pull` and its own `EXACTDOCS_MODELS_DIR`.

**Model licenses.** The weights are third-party, as their model cards at the pinned revisions say:

| Model | What it is | Licence |
|---|---|---|
| `BAAI/bge-small-en-v1.5` | Qdrant's quantized ONNX port | MIT |
| `Xenova/ms-marco-MiniLM-L-6-v2` | an ONNX conversion of `cross-encoder/ms-marco-MiniLM-L-6-v2` | Apache-2.0 |

- Neither repository has a LICENSE or NOTICE file, and `models pull` fetches only the model and
  tokenizer files.
- So `deploy/model-notices/NOTICE` (the attribution, and the MIT and Apache-2.0 texts) is copied to
  `/opt/exactdocs/models/NOTICE`.
- The `-local` image's `org.opencontainers.image.licenses` is `Apache-2.0 AND MIT`.
- A new default model needs its entry there.

**Smoke tests.** Every variant runs `deploy/smoke.sh` (read-only root filesystem, no capabilities)
with no model configured: the `-ai` and `-local` images stay BM25 servers until a role is set.

- The `-ai` image also runs `deploy/check_sqlite_vec.py` (the vector store in the image's own
  Python).
- The `-local` one runs `deploy/smoke_local.py` inside a container started with
  **`--network none`** and the default models on the embedding and reranker roles. It imports the
  fixture, waits for the version to be embedded, and the search must answer with
  `retrieval_mode` `hybrid` and `reranked: true`.

**CI time.**

- The variants are built, checked, scanned and smoke-tested in their own job, in parallel with the
  base image's; `local` builds on the `ai` stages in the same BuildKit.
- On GitHub-hosted runners nothing is cached between runs, so every run builds from scratch and
  pulls the models.

**Locally:** `just docker-build 0.0.0.dev0 ai` (or `local`) builds `exactdocs:build-ai`
(`exactdocs:build-local`), and `just docker-check ai` runs the same check.

### The unit tests

The unit tests add that:

- the default dependency graph in `uv.lock` (from `exactdocs`, optional extras excluded) holds no
  torch, transformers, sentence-transformers, huggingface-hub, onnx, onnxruntime, model2vec,
  tensorflow or pydantic-ai;
- a started app imports none of them (`packages/exactdocs/tests/bootstrap/test_model_free.py`).

The list is `ML_PACKAGES` in `deploy/check_artifacts.py`, shared by the script and the test.
Optional AI extras (`[ai]`) are allowed to carry them: both checks skip `extra ==` requirements.

They also check what `check_artifacts.py image` decides for each variant from what it reads out of
a built image: its installed distributions, its model files and its default models.

!!! note "Chonkie is not banned"
    The chunker is markdown-it-py (issue #27); Chonkie's Markdown recipe needs the HF Hub and
    network, which breaks RUN-02. If it is ever added, these extras must stay off: anything
    pulling torch, transformers, sentence-transformers, onnx/onnxruntime, huggingface-hub or
    model2vec (for Chonkie: the `semantic`, `neural`, `embeddings`, `code` and `all` extras).

## How the base image got to its budget

| Since | Budget | Measured |
|---|---|---|
| first plan | 300 MB | |
| [the first budget](#375-mb-not-300-mb) | 375 MB | 339 MB |
| [E3-11 (#65), DBOS](#400-mb-since-e3-11-65) | 400 MB | 374.5 MB |
| [E10-07 (#87), telemetry](#telemetry-since-e10-07-87) | 400 MB | 384.4 MB |
| [E10-08 (#88), Prometheus](#prometheus-since-e10-08-88) | 400 MB | about +0.6 MB |
| [MCP Apps (#115)](#410-mb-since-mcp-apps-115) | 410 MB | 404.1 MB |

### 375 MB, not 300 MB

This is why 375 MB and not the 300 MB first planned (before DBOS; see below for 400 MB).

- The floor is:
    - the `python:3.14-slim` base (~120 MB);
    - git and ssh (~25 MB git-core plus libraries; Perl is already purged);
    - the virtualenv (167 MB).
- 57 MB of that is precompiled `.pyc`. Dropping it would reach ~297 MB but make every start of a
  read-only container recompile the whole dependency tree. Keeping it is the better trade.
- So the budget is the measured 339 MB plus about 10 % headroom for dependency and Debian security
  updates.[^du]

Raising it needs a reason in the PR; lowering it is the goal if a dependency is dropped.

[^du]: Measured with `du -sxb /`. `docker image inspect` reports 353 MB with overlay2 and only the
    compressed ~115 MB with the containerd store, so it is not used.

### 400 MB since E3-11 (#65)

- Resumable imports run on DBOS 3.3, which imports psycopg at module level (`dbos._utils`,
  `dbos._queue`). So it needs a working psycopg at import time, even though ExactDocs only uses its
  SQLite backend.
- Plain `psycopg` fails to import without a system libpq, and without psycopg DBOS does not import
  at all. Making the import lazy would mean patching DBOS.
- So the image carries `psycopg[binary]` (about 19 MB, with its bundled libpq and OpenSSL), plus
  croniter, python-dateutil and tzdata: about 28 MB in all.
- That took the image from 339 MB to 374.5 MB in CI (Docker image job of #218), 0.5 MB under the
  old 375 MB budget. So the budget was raised to 400 MB: the same headroom (about 7 %) as before,
  for dependency and Debian updates.
- A smaller footprint stays possible behind the same `Checkpoints` port (an ingestion-owned
  checkpoint table instead of DBOS).
- psycopg is LGPL-3.0. Like every Python distribution in the image, it carries its licence in its
  `.dist-info` (see [Licences](licences.md)).

### Telemetry since E10-07 (#87)

384.4 MB.

- The OpenTelemetry SDK and its OTLP/HTTP exporter (with protobuf, googleapis-common-protos and
  requests) are imported only when `EXACTDOCS_TELEMETRY=otlp`, but ship in the image so operators
  can turn them on. #218 measured 374.5 MB before them.
- With Logfire as the SDK, as the Telemetry decision first named, the image was 393.3 MB (6.7 MB of
  headroom). Logfire (a second copy of its package for its migration, plus executing, wrapt and
  opentelemetry-instrumentation) was about 9 MB of that, which is part of why the plain SDK is
  used.
- The 15.6 MB left is about 4 %: the next dependency that needs room should first look for
  something to drop.

### Prometheus since E10-08 (#88)

About +0.6 MB.

- `opentelemetry-exporter-prometheus` and `prometheus-client` (pure Python, no dependencies of their
  own) add about 0.57 MB with their compiled bytecode, measured in a clean virtualenv.
- They are imported only when `EXACTDOCS_METRICS` is on.
- CI's *Docker image* job reports the exact size.

### 410 MB since MCP Apps (#115)

404.1 MB.

- `view_article` and `view_search` render through Prefab UI (`prefab-ui`, pinned), whose renderer is
  a single self-contained page (`app.html`, 6.8 MB, every script and style inlined).
- ExactDocs serves it itself so that a host never loads the UI from a CDN, which keeps the offline
  guarantee. That page is nearly all of the 8 MB the extra adds.
- The maintainer chose to raise the budget by 10 MB rather than move MCP Apps into an optional
  extra, so every install gets them.
- The headroom is now about 1.5 %: the next dependency that needs room must first look for
  something to drop.
