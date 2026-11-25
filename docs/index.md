---
title: ExactDocs
description: A self-hosted MCP server that gives coding agents the docs of the library version you use, verbatim, with the file and commit they came from.
hide:
  - navigation
  - toc
---

<div class="xd-hero" markdown>

# Documentation, word for word

<p class="xd-lede">ExactDocs is a self-hosted MCP server that gives coding agents the docs of the
library version you actually use. Point it at a git repository and it serves the Markdown there,
verbatim, pinned to the tag, branch or commit you imported, with the file and commit each answer
came from.</p>

<p class="xd-actions">
  <a class="md-button md-button--primary" href="getting-started/">Get started</a>
  <a class="md-button" href="mcp/">Connect an agent</a>
  <a class="md-button" href="https://github.com/SirCypkowskyy/ExactDocs">Source on GitHub</a>
</p>

```bash
docker run -d -p 3000:3000 -v exactdocs-data:/data ghcr.io/sircypkowskyy/exactdocs:latest
# or, without Docker
uvx exactdocs serve
```

</div>

<div class="xd-prose" markdown>

!!! abstract "TL;DR"
    - ExactDocs is a self-hosted MCP server: point it at a git repository and agents get its docs
      verbatim, pinned to the tag, branch or commit you imported.
    - The version is a hard filter, and every chunk names its file, heading and commit.
    - `resolve-library-id` and `query-docs` match context7's, so a context7 client needs only a new
      URL.
    - The standard image runs BM25 on SQLite with no model; AI retrieval is optional.
    - Start with `docker run` or `uvx exactdocs serve`, then follow [Getting started](getting-started/index.md).

</div>

<figure class="xd-figure" markdown>

![Two query-docs calls over MCP with the same question, How do I start the sandbox with Docker, one for /acme/payments/v1.3.0 and one for v1.4.0. The first chunk of each reply is shown verbatim, and the lines that differ are highlighted: docs/guide/setup.md and acme/payments:1.3 in v1.3.0, docs/guide/install.md and acme/payments:1.4 in v1.4.0.](assets/screenshots/mcp-light.webp#only-light)
![Two query-docs calls over MCP with the same question, How do I start the sandbox with Docker, one for /acme/payments/v1.3.0 and one for v1.4.0. The first chunk of each reply is shown verbatim, and the lines that differ are highlighted: docs/guide/setup.md and acme/payments:1.3 in v1.3.0, docs/guide/install.md and acme/payments:1.4 in v1.4.0.](assets/screenshots/mcp-dark.webp#only-dark)

<figcaption>An agent asks two versions of the same library one question. Both replies are real
<code>query-docs</code> output from the test fixture library; the highlighted lines are the ones
that differ. Ask about a version that is not imported and the answer is an explicit "not found",
never another version's text.</figcaption>

</figure>

## What you get

<div class="xd-grid" markdown>

<div markdown>

### The version is a hard filter

Every library version is a git ref resolved to a commit SHA, and every search runs inside one
version. In the [benchmark](benchmark/index.md), no configuration returned a chunk of another
version for any of its 321 questions.

</div>

<div markdown>

### The original text, with its source

Markdown and MDX come back as written, and Sphinx reStructuredText as the Markdown it was
converted to on import. Each chunk names its file, heading and commit, and links to the file on
your git host.

</div>

<div markdown>

### Your repositories, public or private

GitHub, GitLab, Bitbucket, Gitea or any git server. You choose the folders and files, and only
those are imported. Branches stay fresh by hand, on a schedule or by webhook.

</div>

<div markdown>

### The tools agents already know

`resolve-library-id` and `query-docs` match context7's, so a client set up for context7 needs only
a new URL. More tools list, browse, read and search one version. See [MCP](mcp.md).

</div>

<div markdown>

### Light until you ask for more

The standard image runs BM25 on SQLite with no model. Hybrid search, rerankers, HyDE and an
agentic mode are optional, on hosted models or on your CPU. See
[Search and AI models](search.md).

</div>

<div markdown>

### It stays on your network

There is no telemetry. The only outbound connections go to the git hosts, model endpoints and
trace collector you configure. Accounts, OpenID Connect and library roles decide who reads what.

</div>

</div>

## What it looks like

<figure class="xd-shot" markdown>

![The ExactDocs reader showing the Caching article of astral-sh/uv 0.13.9: the version picker with commit 6b2d39d, the file tree, the rendered article and its headings on the right.](assets/screenshots/reader-light.webp#only-light){ loading=lazy }
![The ExactDocs reader showing the Caching article of astral-sh/uv 0.13.9: the version picker with commit 6b2d39d, the file tree, the rendered article and its headings on the right.](assets/screenshots/reader-dark.webp#only-dark){ loading=lazy }

<figcaption>The reader: one article of one version, with its commit, its place in the file tree
and its headings.</figcaption>

</figure>

<figure class="xd-shot" markdown>

![The libraries page with 34 libraries, among them Ruff, ty and uv from astral-sh and several Azure docs, each with its project mark, default version and commit, number of versions and articles, when it was last imported and whether it syncs.](assets/screenshots/libraries-light.webp#only-light){ loading=lazy }
![The libraries page with 34 libraries, among them Ruff, ty and uv from astral-sh and several Azure docs, each with its project mark, default version and commit, number of versions and articles, when it was last imported and whether it syncs.](assets/screenshots/libraries-dark.webp#only-dark){ loading=lazy }

<figcaption>Each library with its default version and commit, and how many versions and articles it has.</figcaption>

</figure>

<figure class="xd-shot" markdown>

![The uv library at its default version, 0.13.9, with the version picker open at commit 6b2d39d.](assets/screenshots/library-light.webp#only-light){ loading=lazy }
![The uv library at its default version, 0.13.9, with the version picker open at commit 6b2d39d.](assets/screenshots/library-dark.webp#only-dark){ loading=lazy }

<figcaption>A library and its versions, each a tag, branch or commit pinned to its SHA.</figcaption>

</figure>

<figure class="xd-shot" markdown>

![Search results for cache across every library: the top 20 of 4,438 results, the libraries with their counts on the left, and the results grouped by library and version, each with its heading path, its file and the matching text highlighted.](assets/screenshots/search-light.webp#only-light){ loading=lazy }
![Search results for cache across every library: the top 20 of 4,438 results, the libraries with their counts on the left, and the results grouped by library and version, each with its heading path, its file and the matching text highlighted.](assets/screenshots/search-dark.webp#only-dark){ loading=lazy }

<figcaption>One search across the default version of every library, grouped by library.</figcaption>

</figure>

<figure class="xd-shot" markdown>

![The search playground with the query how do I clear the cache on /astral-sh/uv, ranked by hybrid search and by BM25 side by side.](assets/screenshots/playground-light.webp#only-light){ loading=lazy }
![The search playground with the query how do I clear the cache on /astral-sh/uv, ranked by hybrid search and by BM25 side by side.](assets/screenshots/playground-dark.webp#only-dark){ loading=lazy }

<figcaption>The search playground ranks one query in two retrieval modes side by side, with each
result's BM25 and vector rank.</figcaption>

</figure>

## How well it finds things

<div class="xd-prose" markdown>

The [golden set](benchmark/golden-set.md) is 321 questions about the docs of Starlette, Pydantic,
TanStack Query, Zod and Electron, at three pinned versions each. With no model at all, BM25 puts
a section that answers in the top 5 for 87.6% of the 267 answerable questions, at 52 ms p95.
Hybrid search on a small local embedding model reaches up to 91.0%. Hosted models have not run
yet. [Recommended defaults](benchmark/defaults.md) has the numbers and the known weak spots.

</div>

## Use it

| Page | What is in it |
|---|---|
| [Getting started](getting-started/index.md) | Start the server, create the admin, import a library<br/>use the CLI, private repositories, the sources file, webhooks<br/>accounts, sign-in through an identity provider |
| [MCP](mcp.md) | Connecting Claude, Cursor, VS Code and Codex; tokens; stdio; every tool and resource; context7 over REST |
| [Sources file](sources.md) | Declaring libraries in `exactdocs.sources.yaml`, with `sources plan` and `sources apply` |
| [Configuration](configuration.md) | Every environment variable, the TOML file, sign-in providers and the secret key |
| [Search and AI models](search.md) | Retrieval modes, chunking and tags, AI providers, reranking, agentic search, local models, budgets |
| [Deployment](deployment.md) | Image variants, hardened Docker, reverse proxies, health checks, upgrades, backups, PostgreSQL, Supabase, observability |

## How it is built

| Page | What is in it |
|---|---|
| [Architecture](architecture.md) | The system at a glance, then the modular monolith<br/>domains, ports and adapters, the data model, background jobs, vertical slices<br/>the tests that enforce them |
| [Flows](flows.md) | Import, re-sync, query, retrieval modes and authentication as diagrams |
| [REST API](rest-api.md) | Conventions, authentication, errors, and the library, version, sync and job endpoints |
| [Retrieval evals](evals.md) | The eval suite that compares retrieval modes |
| [Benchmark](benchmark/index.md) | The golden set, method, results and recommended defaults |
| [Branching and releases](releasing.md) | `main` and `develop`, SemVer and PEP 440 versions<br/>tag-driven releases to PyPI and ghcr.io<br/>CI runners, size budgets |

## Where the project is going

| Page | What is in it |
|---|---|
| [User stories](user-stories.md) | The main use case (git repository to Markdown to browsing) as user stories, plus what comes next and later |
| [Delivery plan](plan/index.md) | The issues behind the user stories, by epic and milestone |
| [AI retrieval decisions](decisions/ai-retrieval.md) | Why the AI retrieval modes are built the way they are |

<div class="xd-prose" markdown>

!!! note "Which version this site describes"
    The site is published from the `main` branch, so it describes the latest release. Anything not
    built yet is marked *planned*. The screenshots are taken from the `develop` branch by
    `just screenshots`, with the test fixture libraries and a stand-in embedding model.

About the diagrams:

- They are [Mermaid](https://mermaid.js.org), and CI parses every one of them.
- This site loads Mermaid from unpkg, pinned to 12.3.0 (the version CI checks with).
- That request is made by the documentation site only, never by the running app.

The README, the contributing guide and the agent skills live in the
[repository](https://github.com/SirCypkowskyy/ExactDocs).

</div>
