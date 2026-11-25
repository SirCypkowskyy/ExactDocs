# Local models

!!! abstract "TL;DR"

    - A small embedding model and a cross-encoder can run inside ExactDocs, on the CPU, with the `exactdocs[local]` extra.
    - `exactdocs models pull` is the one command that contacts the Hugging Face Hub.
    - The `-local` image already holds both default models and runs with no network.
    - A `local` profile runs no chat model.

An air-gapped instance, or one whose docs may not leave it, can run a small embedding model and a
cross-encoder inside ExactDocs, on the CPU (fastembed on ONNX Runtime; no torch, no GPU). They come
with the `exactdocs[local]` extra (`uvx --from 'exactdocs[ai,local]' exactdocs serve`) and are
fetched once, by the one command that contacts the Hugging Face Hub:

```bash
exactdocs models pull        # BAAI/bge-small-en-v1.5 (67 MB) and Xenova/ms-marco-MiniLM-L-6-v2 (92 MB)
exactdocs models pull BAAI/bge-base-en-v1.5   # or any fastembed embedding model or cross-encoder
```

```toml
[ai.providers.local]                    # EXACTDOCS_AI__PROVIDERS__LOCAL__KIND=local: required,
kind = "local"                          # a `local:` role without it is warned about at start

[ai.embedding]
model = "local:BAAI/bge-small-en-v1.5"  # <profile>:<model>, 384 dimensions

[ai.reranker]
model = "local:Xenova/ms-marco-MiniLM-L-6-v2"
# timeout: unset means 5 s for a reranker on a `local` profile, the instance's or a library's
# own (2 s otherwise): a CPU reranks 32 long candidates in about 0.2 to 2 s, more with fewer cores
```

The `-local` image already holds both default models, so the same settings in its environment are
all it needs, even with no network at all (CI runs it with `--network none`):

```bash
docker run -d --name exactdocs -p 3000:3000 -v exactdocs-data:/data \
  -e EXACTDOCS_AI__PROVIDERS__LOCAL__KIND=local \
  -e EXACTDOCS_AI__EMBEDDING__MODEL=local:BAAI/bge-small-en-v1.5 \
  -e EXACTDOCS_AI__RERANKER__MODEL=local:Xenova/ms-marco-MiniLM-L-6-v2 \
  -e EXACTDOCS_AI__MODE=hybrid \
  ghcr.io/sircypkowskyy/exactdocs:latest-local
```

bge-small reads at most 512 tokens, so a chunk longer than about 1,800 characters (chunks go up to
8,000) is embedded from its title, heading path and roughly its first 1,800 characters. Full-text
search, reranking and the agent still see all of it.

## Where models live

In `EXACTDOCS_MODELS_DIR`, which defaults to `<data dir>/models`. The
`-local` image sets it to its read-only `/opt/exactdocs/models`, where the two defaults were pulled
when the image was built, so it needs no `models pull` and no network. Each model has a folder of
its own (`BAAI/bge-small-en-v1.5/`) with its ONNX file, its tokenizer and a marker that
`models pull` writes last. A model that is already there is skipped, so a cached directory makes
the command work offline.

## Pinned revisions

The two defaults are pulled at a fixed Hub commit (bge-small's `aa8f8b06`,
MiniLM's `a0914435`), so a pull, and the `-local` image, are reproducible. The marker records the
commit of every model. A default model pulled at another commit is refused at start (pull it
again); other models are pulled at whatever commit `main` points to at the time.

## Never downloaded at run time

Models load from that folder only (fastembed's
`specific_model_path` and `local_files_only`), which never reaches Hub code, so `HF_HUB_OFFLINE` is
not needed; a test with sockets blocked proves that no connection is made. A role whose model is
not there is turned off at start with an error naming the command, and the server starts and
answers BM25:

```text
AI role embedding (local:BAAI/bge-small-en-v1.5) is off: model ... is not in ...: run `exactdocs models pull BAAI/bge-small-en-v1.5`
```

## In process, bounded

Each model is loaded once per process (at start for the instance's roles),
never on the event loop. The embedding jobs' batches run on a pool of their own, one at a time.
What a search waits on (its query embedding, the rerank) runs on another pool, two at a time, so a
search never queues behind ingestion. Each call gives ONNX Runtime half the cores, its memory arena
is off, and a local model embeds at most 16 texts per call, since padding to the longest text costs
memory.

On a 4-core x86_64 machine, embedding the fixture library (3 versions, 61 distinct chunks) with
bge-small took 2.4 to 3.3 s (4.7 to 5.7 s of CPU). The whole process grew from 398 MB (app and
model loaded) to about 495 MB, peaking near 530 MB. With all cores per call, one arena and batches
of 64, it took 4.3 to 5.9 s and 636 MB.

A few limits:

- A local model cannot shorten its vectors. Leave `[ai.embedding] dimensions` unset, or set it to
  the model's own.
- A `local` profile runs no chat model. Use `ollama`, or any `openai-compatible` server, for a local
  LLM.
- A local model is priced at 0, so a US dollar budget is accepted at start and never stops it. Its
  tokens are recorded as `local_tokens` and count toward no token budget, so no budget stops a
  local embedding job, and a search's query embedding and rerank on a local model are never
  refused (see [Budgets and rate limits](budgets.md)).
