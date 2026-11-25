# The golden set

!!! abstract "TL;DR"
    - The benchmarks of E13 (#344) run on the golden set (#345): questions with known answers
      about five real projects' documentation (Starlette, Pydantic, TanStack Query, Zod,
      Electron), each pinned to one of three versions per project.
    - Nothing of these projects is vendored. The pinned commits are fetched into a cache of about
      65 MB, and the whole corpus imports in about 20 seconds.
    - `just golden-validate` checks that every section a case names exists at the pinned commit,
      as ExactDocs' own chunker cuts the article.
    - Agents wrote the cases, so a seeded sample is reviewed independently (#490).

The fixture is synthetic, so the benchmarks use the golden set instead. It lives in
[`packages/exactdocs/evals/golden/`](https://github.com/SirCypkowskyy/ExactDocs/tree/develop/packages/exactdocs/evals/golden):

| File | What it holds |
|---|---|
| `corpus.yaml` | the corpus manifest: per project, the repository, the docs paths it is imported with (`include`, `exclude`, as a library takes them), the licence and attribution, and one pinned commit per version |
| `cases/<project>.yaml` | that project's cases |

- One case file per project, so several people can add cases without conflicts.
- The format is the retrieval dataset's own (Pydantic Evals, the models in
  `retrieval_eval/dataset.py`). `retrieval_eval.golden.load_golden()` reads every file as one
  dataset.

## The cache

The commands fetch each pinned commit with `git fetch --depth 1` into a cache outside the
repository:

- `$XDG_CACHE_HOME/exactdocs/golden` (`~/.cache/exactdocs/golden`);
- one bare repository per project, about 65 MB in all;
- `--cache-dir` changes it.

```bash
just golden-validate                      # fetch what is missing, then check every case
just golden-validate --projects zod       # one project's sections (the rules are checked for all)
just golden-validate --offline            # no network: the cache must already hold the commits
just golden-import                        # fetch, then import every pinned version for real
just golden-import --data-dir ./golden-data --report out.json
```

`golden-import`:

- imports each version with the real importer at exactly its pinned commit, from the cache (the
  same import path as the fixture, `fixture_import.importer`);
- imports into a model-free instance (a temporary data directory unless `--data-dir` names one);
- records, per version, the commit the catalog stored, the files imported, the import's problems
  and its time, in `reports/evals/golden-import.json`;
- fails when a recorded commit is not the pinned one.

The whole corpus imports in about 20 seconds.

## The corpus

| Project | Versions (pinned commit) | Docs paths |
|---|---|---|
| [Starlette](https://github.com/encode/starlette) | 0.27.0 (`0c4b68a`)<br/>0.52.1 (`e5b8a5d`)<br/>1.10.0 (`8aa828c`) | `docs/` |
| [Pydantic](https://github.com/pydantic/pydantic) | v1.10.22 (`5e6e87f`)<br/>v2.5.3 (`9f58e78`)<br/>v2.14.3 (`ea492e0`) | `docs/` |
| [TanStack Query](https://github.com/TanStack/query) | v4.36.1 (`6532ed3`)<br/>v5.0.0 (`3be9b45`)<br/>v5.90.3 (`4d8da1e`) | `docs/` |
| [Zod](https://github.com/colinhacks/zod) | v3.23.8 (`ca42965`)<br/>v4.0.17 (`cc63f95`)<br/>v4.6.7 (`b500a2e`) | `README.md`<br/>`packages/docs/content/` |
| [Electron](https://github.com/electron/electron) | v30.0.0 (`c37c7fd`)<br/>v38.0.0 (`7943386`)<br/>v45.3.2 (`9ee9e77`) | `docs/` |

| Project | Licence, attribution | What it brings |
|---|---|---|
| Starlette | BSD-3-Clause, © 2018 Encode OSS Ltd. | a small Markdown guide; 1.0 removed the startup and shutdown handlers |
| Pydantic | MIT, © 2017 to present Pydantic Services Inc. and individual contributors | a large MkDocs guide; v1 to v2 moved most pages; admonitions and content tabs; API pages that are mkdocstrings stubs |
| TanStack Query | MIT, © 2021-present Tanner Linsley | guides and API reference, one tree per framework (near-duplicates); renamed options; every page moved between v5.0.0 and v5.90.3 |
| Zod | MIT, © 2025 Colin McDonnell | v3: one very long README; v4: an MDX site with JSX components and imports |
| Electron | MIT, © Electron contributors, © 2013-2020 GitHub Inc. | a large hand-written API reference, tutorials, a breaking-changes page |

- None of them ships a separate licence for its documentation: the repository's licence covers
  the docs tree (no licence file or notice under the docs paths at the pinned commits).
- `corpus.yaml` holds the full commit SHAs. Each was resolved from the release tag with
  `git ls-remote --tags` (the peeled commit of an annotated tag).

## A case

```yaml
- name: 'tanstack-query v5.0.0: What happened to the cacheTime option?'
  inputs:
    project: tanstack-query
    version: v5.0.0
    query: 'What happened to the cacheTime option?'
  metadata: {kind: version-change}
  expected_output:
    hits:
    - {version: v5.0.0, article: docs/react/guides/migrating-to-v5.md, heading_path: [Breaking Changes, Rename cacheTime to gcTime]}
    reference: v5 renames `cacheTime` to `gcTime` ("garbage collect" time); it only applies once a
      query is unused, after which its data is garbage collected.
    facts:
    - cacheTime is renamed to gcTime
    - it only takes effect once a query is no longer used
    - after that time the unused data is garbage collected
```

| Field | What it holds |
|---|---|
| `inputs` | the question (`query`), the `project` (the file it is in) and the `version` (a version name in `corpus.yaml`) |
| `metadata.kind` | exactly one kind (below) |
| `expected_output.hits` | the sections that answer it (below) |
| `expected_output.reference` | a short reference answer, as the pinned docs give it; for an unanswerable case, a sentence saying the version does not cover it |
| `expected_output.facts` | the short facts a correct answer must contain, each checkable on its own; none for an unanswerable case |

The kinds:

| Kind | The question |
|---|---|
| `identifier-lookup` | an API name, option or command |
| `how-to` | steps to do something |
| `conceptual` | what something is or why it behaves so |
| `version-change` | what changed in or by this version |
| `cross-page` | needs sections of at least two articles |
| `unanswerable` | this version's docs do not answer it |

### Expected sections

Each hit is the article path and the heading path from the top heading, as ExactDocs cuts the
article ([What `golden-validate` checks](#what-golden-validate-checks)). An `unanswerable` case
has none.

- Each section is a **part** a complete answer needs ("all of").
- A section marked `alternative: true` answers the same part as the section listed before it, as
  well as that one does, and either is enough ("any of", #501).
- List each part first, then its alternatives:

  ```yaml
  hits:
  - {version: v4.36.1, article: docs/react/reference/useQuery.md, heading_path: []}
  - {version: v4.36.1, article: docs/react/guides/important-defaults.md, heading_path: [], alternative: true}
  - {version: v4.36.1, article: docs/react/guides/caching.md, heading_path: [Basic Example], alternative: true}
  ```

- A `cross-page` case lists two parts or more in different articles. A reference page and a
  guide that both state the answer are alternatives of one part.

Every field the golden set adds has a default, so the fixture dataset and its fingerprint are
unchanged.

## What `golden-validate` checks

Every case file must load as the dataset's models, and every case must:

- have a unique `name`, a golden `kind`, the `project` its file is named after, and a `version`
  the manifest pins;
- have a reference answer;
- name sections and facts unless it is `unanswerable`, and neither when it is;
- name sections of the case's own version only, none of them twice;
- start with a part (an alternative follows the part it answers, or the file does not load);
- for `cross-page`, need parts of two articles or more, alternatives aside;
- name only sections that exist **at the pinned commit**:
    - the article is read from the cache and must be selected by the project's docs paths;
    - its heading path must be one of the chunks the importer's own parser and chunker
      (`parse_article`, `MarkdownChunker` with no settings, which cuts at every heading) cut it
      into.

So a case can only name a section ExactDocs produces, and moving the pins (or changing how
articles are cut) shows every case that no longer holds.

It also checks the review's verdicts, `review.yaml` beside the case files
([Reviewing the golden set](#reviewing-the-golden-set)):

- a `correct` or `fixed` case is in the set, and a `removed` one is not;
- no case is reviewed twice;
- a wrong case names its problems and says why;
- every kind of every project has the sample's number of entries.

It prints every broken case (`<case>: <problem>`, with the closest existing sections when only
the heading path is wrong) and exits with 1.

!!! info "Where it runs"
    `uv run pytest` checks the rules on the real files in CI. The section check needs the cache,
    so it runs in pytest only where the cache already holds the commits (CI skips it), and with
    `just golden-validate`.

## Adding a case

1. Pick the project and version, and read the page at the pinned commit, e.g.
   `git -C ~/.cache/exactdocs/golden/zod.git show v4.6.7:packages/docs/content/api.mdx` (the
   cache tags each pinned commit with its version name).
2. Write the case in `cases/<project>.yaml` as above.
    - Start the name with `<project> <version>: ` and quote the question.
    - Write `inputs` in block style: a question with `[`, `]`, `,`, `?` or `: ` breaks a `{...}`
      flow mapping.
    - A reference containing `: ` needs quotes or `>-`.
3. Take the heading path from the source: the headings from the top one down to the section, as
   plain text (no backticks or links). Text before the first heading has the path `[]`.
4. Run `just golden-validate --projects <project>`. A wrong path lists the closest sections the
   article has; copy the right one.
5. Check the facts against the page once more: each must be stated there, at that version.

### Pitfalls the corpus shows

| Pitfall | What to do |
|---|---|
| No H1 | many pages put their title in front matter (Zod v4, TanStack Query, Starlette), so their heading paths start at the first H2; Zod v3's README starts at H2 too |
| TanStack Query framework pages | the Vue, Solid, Svelte and Angular pages hold only the code that replaces the React page's examples on the website (front matter `ref:`); the prose is only on the React page, so name the React page |
| TanStack Query API reference | its pages have no headings: one section, `[]` |
| Zod v4 MDX | some real headings come out as code ([below](#zod-v4-mdx)); such a section cannot be named until the importer handles it |
| Pydantic v1.10 | it pulls its code examples in with `{!.tmp_examples/...!}`: the code is not in the imported text, only the prose is |
| Pydantic v2 API pages | `docs/api/` holds mkdocstrings stubs |
| Unanswerable | the pinned docs must not answer it at all ([below](#unanswerable-cases)) |

#### Zod v4 MDX

A JSX tag on its own line (`</Tab>`) directly before a code fence, and MDX comments
`{/* ... */}` around fences, make CommonMark pair the fences wrongly. So some real headings come
out as code (`## The error param` in `error-customization.mdx`). The validation refuses such a
section, and the ingestion benchmark counts such headings in `headings_missed`.

#### Unanswerable cases

Unanswerable means the pinned docs do not answer it at all. Search the whole docs tree at that
commit (`git grep`) before writing one: a third-party page that mentions the name is enough to
make it answerable.

## Reviewing the golden set

Agents wrote and checked the cases, so a sample of them is reviewed independently (#490). The
result is on [Golden set](../benchmark/golden-set.md#the-independent-review).

```bash
just golden-review sample              # draw the sample, write reports/golden-review/sheet.md
just golden-review sample --seed 7 --per-stratum 5 --no-text
just golden-review checks              # whole-set checks: reports/golden-review/checks.md, .json
just golden-review summary             # the recorded review's verdicts and error rate
```

### The sample

`sample` draws `--per-stratum` cases (3 by default) of every kind in every project, at random with
`--seed` (490 by default).

- Each stratum is drawn with its own generator, from its cases in name order, so the same seed and
  cases give the same sample.
- It writes a sheet with, per case, the question, version, kind, reference answer, facts and
  sections, each linked to the source at the pinned commit.
- With the cache (the default) the sheet also holds:
    - the text of each expected section;
    - the sections of that version closest to the question and reference;
    - the same section and the closest ones in the neighbouring versions.
- `review-draft.yaml` lists the sampled cases with the verdict left blank.

### The verdicts

The verdicts go in `packages/exactdocs/evals/golden/review.yaml`:

```yaml
sample: {seed: 490, per_stratum: 3, drawn_from: 'sha256:39f6f9d5e909d128'}
entries:
- case: 'zod v4.6.7: Is there a util ...'
  project: zod
  kind: identifier-lookup        # the stratum it was drawn from; a fix may change the case's kind
  verdict: fixed                 # correct, fixed (the case was corrected) or removed
  problems: [unsupported-fact]   # empty when correct
  reviewer: independent review agent (adversarial brief; not the agent that wrote the cases)
  date: 2026-11-23
  note: The source line that proves the defect, and what was changed.
```

- `drawn_from` is the golden set's fingerprint when the sample was drawn, before any fix. Fixes
  change the cases' sections and kinds, so drawing again from today's set gives another sample.
- A fix that rewrites a question renames the case. Its entry names the new case and keeps the old
  name in `was`.

The problem categories:

| Problem | The case |
|---|---|
| `unsupported-fact` | lists a fact the expected sections do not state at that version, or only imply |
| `wrong-reference` | has a reference answer that is wrong or incomplete for that version |
| `missing-section` | leaves out another section of that version that answers it as well |
| `wrong-section` | names a section that does not answer it |
| `wrong-kind` | has the wrong kind; `cross-page` when one article states every fact |
| `answerable` | is `unanswerable`, but its version's docs answer it |
| `not-a-change` | is a `version-change` whose change the neighbouring versions contradict |
| `ambiguous` | has more than one fair answer, or none without guessing |
| `duplicate` | asks what another case asks of the same version |

### Whole-set checks

`checks` runs over the whole set and needs the cache. It cuts every article of every pinned version
as the importer does (every heading starts a section) and compares words: lower-case, stemmed,
stop words left out, each weighted by its inverse document frequency in that version.

**Lexical overlap**, per answerable case:

- the weighted share of the question's words its best expected section holds;
- the same for the best section that is not expected;
- the expected section's rank among all sections of the version;
- the longest run of words the question shares with an expected section. A run of 5 words or
  more, 3 of them content words, is listed as copied.

A question written from its section's words would favour keyword search (BM25).

**Near-duplicate questions**: pairs of one project that share at least half their content words
(Jaccard), same version or not.

**The vocabulary of every `unanswerable` case**:

- its words no section of its version holds;
- the three sections holding most of them;
- one section with 75% of the weighted words is flagged to check by hand.

Synonyms are not searched; the reviewer does that.

The tests (`tests/evals/test_golden_review.py`, `golden_review.feature`) run on a tiny local
repository. One checks the recorded `review.yaml` against the real case files in CI.
