# Golden set

The golden set (#345) is 321 questions with known answers about the documentation of five open
source projects, three pinned versions each. Every case names the version it asks about, the
sections of that version's docs that answer it, a short reference answer and the facts a correct
answer must contain. The benchmarks import each version with the real importer and ask the
questions in that version's library.

It lives in
[`packages/exactdocs/evals/golden/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/golden):
`corpus.yaml` pins the projects and versions, and `cases/<project>.yaml` holds each project's
cases. Nothing of these projects is stored in this repository. `just golden-validate` and the
benchmarks fetch each pinned commit (`git fetch --depth 1`, about 65 MB in all) into a cache
outside it.

## The corpus

Each version is pinned to the commit its release tag points at. None of the projects ships a
separate licence for its documentation, so the repository's licence covers the docs tree;
`corpus.yaml` holds the full commits and what each project brings to the set (an MkDocs site, MDX
pages, one long README, a large API reference, framework variants of the same pages).

<!-- bench:golden -->
| Project | Versions (pinned commit) | Docs paths | Licence | Attribution |
|---|---|---|---|---|
| [Starlette](https://github.com/encode/starlette) | 0.27.0 (`0c4b68a`), 0.52.1 (`e5b8a5d`), 1.10.0 (`8aa828c`) | `docs/` | BSD-3-Clause | Copyright © 2018, Encode OSS Ltd. |
| [Pydantic](https://github.com/pydantic/pydantic) | v1.10.22 (`5e6e87f`), v2.5.3 (`9f58e78`), v2.14.3 (`ea492e0`) | `docs/` | MIT | Copyright (c) 2017 to present Pydantic Services Inc. and individual contributors. |
| [TanStack Query](https://github.com/TanStack/query) | v4.36.1 (`6532ed3`), v5.0.0 (`3be9b45`), v5.90.3 (`4d8da1e`) | `docs/` | MIT | Copyright (c) 2021-present Tanner Linsley |
| [Zod](https://github.com/colinhacks/zod) | v3.23.8 (`ca42965`), v4.0.17 (`cc63f95`), v4.6.7 (`b500a2e`) | `README.md`, `packages/docs/content/` | MIT | Copyright (c) 2025 Colin McDonnell |
| [Electron](https://github.com/electron/electron) | v30.0.0 (`c37c7fd`), v38.0.0 (`7943386`), v45.3.2 (`9ee9e77`) | `docs/` | MIT | Copyright (c) Electron contributors; Copyright (c) 2013-2020 GitHub Inc. |

| Kind | starlette | pydantic | tanstack-query | zod | electron | All | Example |
|---|---|---|---|---|---|---|---|
| `identifier-lookup` | 10 | 10 | 11 | 11 | 10 | 52 | starlette 0.52.1: What is the default max_age of SessionMiddleware? |
| `how-to` | 11 | 11 | 10 | 11 | 10 | 53 | pydantic v2.14.3: How do I add a check that runs after Pydantic has validated a field? |
| `conceptual` | 11 | 11 | 10 | 10 | 10 | 52 | tanstack-query v5.90.3: Why does my query refetch every time the window gets focus? |
| `version-change` | 11 | 12 | 11 | 11 | 12 | 57 | zod v4.0.17: What should I use instead of .strict() and .passthrough() on objects? |
| `cross-page` | 11 | 11 | 10 | 10 | 11 | 53 | electron v30.0.0: BrowserView is deprecated. What do I replace it with and how do I place the new view in a window? |
| `unanswerable` | 10 | 11 | 11 | 10 | 12 | 54 | starlette 0.27.0: How do I send a 103 Early Hints response? |
| all | 64 | 66 | 63 | 63 | 65 | 321 | |
<!-- /bench -->

## Question kinds

Each case has exactly one kind (`metadata.kind`):

- `identifier-lookup`: an API name, option or command;
- `how-to`: the steps to do something;
- `conceptual`: what something is or why it behaves as it does;
- `version-change`: what changed in or by this version;
- `cross-page`: the answer needs sections of at least two articles;
- `unanswerable`: this version's docs do not answer it, so the case names no section. A good
  answer says so instead of answering from another version or from memory.

The table above counts the cases per kind and project, with one example question per kind.

## How the cases were written and checked

Every case was written by an agent from the source at its pinned commit: the facts are taken from
that version's text, and each `unanswerable` case was searched for (`git grep`) in that version's
whole docs tree. The same agent then checked each case against the source. **No person has
reviewed the cases yet**, so the set may hold mistakes a reader would catch; a spot check is
welcome, and a wrong case is fixed like any other bug.

What a machine checks, on every case, with `just golden-validate`:

- the case loads as the dataset's models, has a unique name, one of the six kinds, the project of
  its file and a version the corpus pins;
- it has a reference answer, and sections and facts unless it is `unanswerable` (which has
  neither);
- every section it names exists at the pinned commit as a chunk the importer's own parser and
  chunker produce, so a case can only name a section ExactDocs can return.

CI checks the rules on every pull request; the section check needs the corpus cache, so it runs
locally and wherever the cache is present. Details are in
[What `golden-validate` checks](../evals.md#what-golden-validate-checks).

## Adding a case

Pick a project and version, read the page at the pinned commit, write the case in
`cases/<project>.yaml` and run `just golden-validate --projects <project>`: a wrong heading path
lists the closest sections the article has. The step-by-step guide and the pitfalls this corpus
shows (pages without H1, TanStack Query framework pages, Zod's MDX, Pydantic's includes) are in
[Adding a case](../evals.md#adding-a-case). Adding or changing a case changes the golden set's
fingerprint, so the recorded runs and these pages are refreshed in the same pull request
([Method](method.md#refreshing-these-pages)).
