# Golden set

!!! abstract "TL;DR"
    - 321 questions with known answers about the docs of five open source projects, three pinned
      versions each, in six question kinds.
    - `just golden-validate` checks that every section a case names exists as a chunk the importer
      produces.
    - No person has reviewed the cases. An independent agent review of a 90-case sample found 23
      wrong in some way (none wrong at its core, mostly missing sections) and fixed them; the other
      231 cases were not reviewed.

The golden set (#345) is 321 questions with known answers about the documentation of five open
source projects, three pinned versions each. Every case names:

- the version it asks about;
- the sections of that version's docs that answer it;
- a short reference answer;
- the facts a correct answer must contain.

The benchmarks import each version with the real importer and ask the questions in that
version's library.

It lives in
[`packages/exactdocs/evals/golden/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/golden):

| File | Holds |
|---|---|
| `corpus.yaml` | the projects and versions, pinned |
| `cases/<project>.yaml` | each project's cases |

!!! note "The projects' docs are not in this repository"
    `just golden-validate` and the benchmarks fetch each pinned commit (`git fetch --depth 1`,
    about 65 MB in all) into a cache outside it.

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
| `how-to` | 12 | 12 | 11 | 13 | 10 | 58 | pydantic v2.14.3: How do I add a check that runs after Pydantic has validated a field? |
| `conceptual` | 11 | 11 | 10 | 11 | 10 | 53 | tanstack-query v5.90.3: Why does my query refetch every time the window gets focus? |
| `version-change` | 11 | 12 | 11 | 10 | 12 | 56 | zod v4.0.17: What should I use instead of .strict() and .passthrough() on objects? |
| `cross-page` | 10 | 10 | 9 | 8 | 11 | 48 | electron v30.0.0: BrowserView is deprecated. What do I replace it with and how do I place the new view in a window? |
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

Every case was written by an agent from the source at its pinned commit:

- the facts are taken from that version's text;
- each `unanswerable` case was searched for (`git grep`) in that version's whole docs tree;
- the same agent then checked each case against the source.

What a machine checks, on every case, with `just golden-validate`:

- the case loads as the dataset's models, has a unique name, one of the six kinds, the project of
  its file and a version the corpus pins;
- it has a reference answer, and sections and facts unless it is `unanswerable` (which has
  neither);
- every section it names exists at the pinned commit as a chunk the importer's own parser and
  chunker produce, so a case can only name a section ExactDocs can return.

!!! info "Where the checks run"
    CI checks the rules on every pull request. The section check needs the corpus cache, so it
    runs locally and wherever the cache is present. Details are in
    [What `golden-validate` checks](../evals/golden-set.md#what-golden-validate-checks).

## The independent review

No person has reviewed the cases. A second agent did (#490):

- its brief was to find what is wrong rather than to confirm it;
- it is not the agent or the prompt that wrote them;
- it reviewed a random sample: `just golden-review sample` drew three cases of each kind in each
  project, 90 in all, with a fixed seed, from the set as it was before any fix.

For each case it read the docs at the pinned commit and checked:

- that the expected sections state every fact, not merely imply it;
- that the reference answer is right for that version;
- that no other section of that version answers the question as well without being listed;
- the kind (a `cross-page` case is wrong when one article states every fact);
- for `unanswerable` cases, that no page of that version answers it, searching the whole docs tree
  for the question's words, synonyms and API names;
- for `version-change` cases, the neighbouring versions.

Each verdict is in
[`evals/golden/review.yaml`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/golden/review.yaml):
correct, fixed or removed, the problems, and a note quoting the source that proves each one.
`just golden-validate` checks the file against the cases. How the review works and what each
problem means: [Reviewing the golden set](../evals/golden-set.md#reviewing-the-golden-set).

<!-- bench:golden-review -->
- Sample: 90 cases, 3 per kind and project, seed 490, drawn from golden set `sha256:39f6f9d5e909d128`.
- Reviewed by: independent review agent (adversarial brief; not the agent that wrote the cases), 2026-11-23.
- Verdicts: 67 correct, 23 fixed, 0 removed.
- Wrong cases: 23 of 90, 25.6% (95% Wilson interval 17.7% to 35.4%).

| Problem | Cases |
|---|---|
| `unsupported-fact` | 3 |
| `missing-section` | 17 |
| `wrong-kind` | 6 |

| Kind | Wrong / reviewed |
|---|---|
| `identifier-lookup` | 3 / 15 |
| `how-to` | 3 / 15 |
| `conceptual` | 4 / 15 |
| `version-change` | 8 / 15 |
| `cross-page` | 5 / 15 |
| `unanswerable` | 0 / 15 |

| Project | Wrong / reviewed |
|---|---|
| electron | 3 / 18 |
| pydantic | 3 / 18 |
| starlette | 4 / 18 |
| tanstack-query | 9 / 18 |
| zod | 4 / 18 |
<!-- /bench -->

The sample is a stratified one with 10 to 12 cases per stratum, so the plain share of wrong cases
above is within half a point of the share weighted by stratum size (25.3%). What the review found
(three cases had two problems each):

- **No case was wrong at its core.** No reference answer was wrong for its version, every expected
  section answers its question, and all 15 `unanswerable` cases held: none is answered anywhere in
  its version's docs.
- **Missing sections, 17 cases.** Another section of the same version answers the question as
  well. Each section was added to its case. The kinds of section:
    - the API reference page next to the guide the case names (`useMutation`'s `scope`,
      `useQuery`'s `keepPreviousData`, `refetchOnWindowFocus`);
    - a tutorial that repeats the table of a guide;
    - the ESLint rule page that says not to put a query result in a dependency array;
    - a release note for a "since when" question;
    - a deprecation note in the breaking changes.
- **Wrong kind, 6 cases.** Five `cross-page` cases have every fact in one article (the second
  article adds nothing), and one `version-change` case asks about no change. They are now `how-to`
  and `conceptual`.
- **Unsupported facts, 3 cases.** A fact stated only in a neighbouring section (a codemod, the
  mutation variant of a util) or only implied (that `lifespan` replaces `on_startup`). The facts
  and reference answers were narrowed to what the sections state.
- **By kind**, `version-change` cases were wrong most often (8 of 15), then `cross-page`; by project,
  TanStack Query (9 of 18), whose guides and API reference pages often say the same thing.

!!! warning "Most cases are not reviewed"
    The 23 wrong cases of the sample are fixed; the other 231 cases were not reviewed. If the
    sample is representative, about 59 of them (41 to 82 at the interval's ends) have problems of
    the same kinds, mostly missing sections.

What this means for the results:

- The sections the review added answer the question as well as the one listed, so they are
  marked as **alternatives** of the part they answer (`alternative: true`, #501): 21 sections in
  the 17 cases. 4 of those cases still need two parts.
- recall@k and MRR count a hit on any section a case lists, and section recall and nDCG@10 count
  each part once. A configuration or tool that returns the other answering section (often an API
  reference page) is not scored a miss ([Method](method.md#retrieval-metrics)).
- Until #501, recall@k counted only the first listed section, and these sections counted for
  nDCG@10 and section recall as parts the answer also needed.

The golden set's fingerprint changed three times, and the [ingestion run](ingestion.md) and the
[retrieval run](retrieval.md) were recorded again each time (the last time also the text scorer's
calibration and the [Grounded Docs run](comparison.md)):

| Change | Fingerprint |
|---|---|
| before the review | `sha256:39f6f9d5e909d128` |
| the fixes | `sha256:7dd51c59057c279a` |
| marking the alternatives | `sha256:a00997851150e3b0` |
| the `config-both` case names its heading without `{#config-both}`, as the chunker cuts it since #571 | `sha256:100484c7ccdb1b89` |

### Wording

`just golden-review checks` measures how the questions are worded against the docs of their
version (on 2026-11-23, after the fixes):

- Over the 267 answerable cases, the expected section holds on average 60.7% of a question's
  content words (weighted by how rare each word is in that version) and the best other section
  59.3%. The expected section is the best match on words for 58.8% of the questions.
- 6 questions (2%) share a run of five words or more with their section, two of them because they
  quote an error message.
- `identifier-lookup` and `version-change` questions lean towards their section (it is the best
  match for 69% and 64% of them), as they name the API or the change. `how-to` and `conceptual`
  questions are worded closer to other sections than to their own (by 0.6 and 3.0 points).
- No two questions of the same version are near-duplicates; 4 pairs ask the same thing of two
  versions, by design.

The questions were paraphrased, not copied from their sections, so their wording does not favour
keyword search (BM25) over embeddings.

## Adding a case

1. Pick a project and version.
2. Read the page at the pinned commit.
3. Write the case in `cases/<project>.yaml`.
4. Run `just golden-validate --projects <project>`. A wrong heading path lists the closest
   sections the article has.

The step-by-step guide and the pitfalls this corpus shows (pages without H1, TanStack Query
framework pages, Zod's MDX, Pydantic's includes) are in [Adding a case](../evals/golden-set.md#adding-a-case).

!!! note
    Adding or changing a case changes the golden set's fingerprint, so the recorded runs and these
    pages are refreshed in the same pull request ([Method](method.md#refreshing-these-pages)).
