# Local models and the vector store

!!! abstract "TL;DR"
    - Local embeddings and the cross-encoder run on fastembed 0.9.1 and ONNX Runtime (no torch) in
      `exactdocs[local]`. Defaults: `BAAI/bge-small-en-v1.5` and `Xenova/ms-marco-MiniLM-L-6-v2`.
    - Only `exactdocs models pull` contacts the Hugging Face Hub. At run time models load from
      `EXACTDOCS_MODELS_DIR`, and a missing model disables its role.
    - Image budgets: base 400 MB, `-ai` 560 MB, `-local` 950 MB. The `-local` models are baked in
      at build time so the image works with `--network none`.
    - Vectors sit behind one `VectorIndex` port, one table per embedding space. Search is exact
      within the version's manifest (sqlite-vec 0.1.9 or pgvector `<=>`), with no ANN index.
    - Changing the embedding model creates a new space; until a version is covered it answers BM25
      with `fallback_reason: embedding_in_progress`.

## Local and offline models

- **fastembed 0.9.1 on ONNX Runtime 1.31.0** (CPU) in an `exactdocs[local]` extra: embeddings
  (`TextEmbedding`) and a cross-encoder (`TextCrossEncoder`) without torch. sentence-transformers
  was rejected: it needs torch (hundreds of MB) and is not installable from pydantic-ai on 3.14.
- **Defaults:** `BAAI/bge-small-en-v1.5` (384 dimensions, 67 MB quantized ONNX) and
  `Xenova/ms-marco-MiniLM-L-6-v2` (91 MB). Other fastembed models can be configured; the eval
  suite decides whether the defaults change.
- **No download at run time.**
    - `exactdocs models pull` is the only command that contacts the Hugging Face Hub. It stores
      models in **`EXACTDOCS_MODELS_DIR`** (default `<data dir>/models`; the `-local` image sets it
      to its read-only `/opt/exactdocs/models`).
    - At run time models load from that directory only (`specific_model_path`,
      `local_files_only`). fastembed never reaches Hub code, so `HF_HUB_OFFLINE` is not needed
      (#278).
    - A missing model disables the role at start with a message. It is never fetched.
- A local **LLM** is out of scope for in-process inference: use the `ollama` kind (or vLLM,
  llama.cpp's server, LM Studio as `openai-compatible`).

### Image variants

Measured on 2026-11-07 (Python 3.14, x86_64, site-packages with bytecode, which the image keeps):

| Variant | Contents | Estimated | Budget |
|---|---|---|---|
| `exactdocs:<v>` | as today: BM25, SQLite and PostgreSQL | 384 MB | **400 MB** (unchanged) |
| `exactdocs:<v>-ai` | `exactdocs[ai]`: +141 MB (`anthropic` 17, `openai` 16, `pydantic_monty` 12, `pydantic_ai` 10, google-genai about 11, harness 6, ...), plus about 5 MB for `azure-identity` | 531 MB | **560 MB** |
| `exactdocs:<v>-local` | `exactdocs[ai,local]`: +196 MB (`onnxruntime` 63, numpy 57, pillow 20, tokenizers 12, ...) and the two default models (158 MB) in `/opt/exactdocs/models` (`EXACTDOCS_MODELS_DIR`) | 887 MB | **950 MB** |

- The base image and the wheel stay **model-free** (RUN-02): the `ML_PACKAGES` checks keep
  ignoring `extra ==` requirements, and also apply to the `-ai` image; only `-local` may hold
  ONNX Runtime and model files.
- `uvx exactdocs` stays BM25-only; `uvx --from 'exactdocs[ai]' exactdocs serve` and
  `'exactdocs[ai,local]'` add the extras.
- `[ai]` lists `pydantic-ai-harness` and `pydantic-monty` instead of
  `pydantic-ai-harness[codemode]`: that extra also pulls a DuckDuckGo search client (`ddgs`,
  `primp`, `lxml`: about 27 MB) that Code Mode does not import.
- CI builds the three targets of one Dockerfile and checks each budget (#246).
    - CI (arm64, PR #285) measured **387.1**, **520.4** and **866.5 MB** (amd64: 353.0, 492.0 and
      847.9 MB).
    - So the budgets stay as set: 7.1 % of headroom for `-ai`, and 8.8 % for `-local`, kept on
      purpose as room for a default-model update. `docs/releasing/images.md`, *Size and model-free
      budgets*, has the reasoning.
- The `-local` models are baked in at build time, not pulled at first start: the image must work
  with `--network none`.
    - They are pulled at their pinned revisions, and their ONNX files are checked against pinned
      sha256 digests.
    - Their licenses (MIT for bge-small, Apache-2.0 for the cross-encoder) ship with them in
      `/opt/exactdocs/models/NOTICE`.

## Vector store

- **One driven port, `VectorIndex`** (#242): create or retire a space, upsert and delete vectors by
  chunk key, find the nearest chunks within one manifest, report a manifest's coverage. In-memory,
  SQLite (#242) and pgvector (#243) adapters run one contract test.
- **Embedding space.**
    - A space is one (profile kind, model, dimensions, input format version). It is recorded in
      `retrieval_embedding_spaces` with its state (`building`, `active`, `retired`).
    - Its vectors live in **one table per space** (`retrieval_vec_<space>`), created and dropped by
      the adapter, like the search index tables of `exactdocs reindex`.
    - A table per space gives a fixed `vector(<dimensions>)` type on PostgreSQL and makes mixing
      two models impossible.
- **Keys and dedup.**
    - A vector belongs to a `retrieval_chunks` row. That row is already shared by every version
      holding the same blob with the same chunking, so a blob is embedded once.
    - Garbage collection removes vectors with their chunk sets.
- **Search is exact, scoped to the manifest.**
    - Every query is pinned to one version, so it scans at most that version's chunks (thousands
      to tens of thousands): sqlite-vec's `vec_distance_cosine` over float32 BLOBs, pgvector's
      `<=>`.
    - No ANN index: exact results keep evals reproducible and need no tuning. Exact search also
      avoids pgvector's 2,000-dimension index limit.
    - HNSW per space is a follow-up if #242's benchmark (50,000 vectors of 1,024 dimensions, p95
      under 150 ms) fails on a real instance.
- **sqlite-vec 0.1.9** (2026-03-31, the latest stable; 0.1.10 is still alpha).
    - It is loaded per connection, by the first search on that connection or by the availability
      check. The check runs only once an embedding model is configured, so that hybrid can be
      reported unavailable before any space exists. With no embedding model it is never imported.
    - A connection that searches also gets `PRAGMA mmap_size` (1 GiB of address space), which cut
      the p95 of #242's benchmark by about a fifth.
    - It replaces the earlier "numpy brute force" decision: the distance runs in SQL, next to the
      manifest join, and numpy is not needed.
    - Verified on uv's Python 3.14 build (`enable_load_extension`, `vec_distance_cosine`, `vec0`).
      The image runs `python:3.14-slim-trixie`, so #242 repeats the check in the built image.
    - A Python built without loadable extensions reports hybrid as unavailable instead of failing.
- **Model change.**
    - Changing the embedding model, its dimensions or the input format creates a new space and
      queues `embed` jobs.
    - Until a version is covered by the new space it answers BM25 with
      `fallback_reason: embedding_in_progress` (the old space cannot be queried without the old
      model).
    - The old space is retired and dropped once the new one covers every version.
    - Changing only a base URL keeps the space; `exactdocs ai reembed` forces a new one.
- **What is embedded:** the chunk's article title and heading path, then its text (input format
  1). Queries are embedded as queries where the model distinguishes them.
