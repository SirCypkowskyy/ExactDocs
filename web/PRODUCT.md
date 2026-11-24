# Product

<!-- impeccable:product-schema 1 -->

Facts below come from the repository (README.md, docs/user-stories.md), the maintainer's brief for
issues #426, #427 and #434, and an interview with the maintainer on 2026-11-23. Lines marked
*(inferred)* have not been confirmed.

## Platform

web

## Users

The primary customer is an organisation: a platform or developer-experience team deploys one
instance for many engineers (confirmed 2026-11-23). A solo developer on localhost or a homelab is a
secondary audience and must keep working with zero external services.

- **Operators (admins)** of a self-hosted instance: developers or platform engineers who add git
  repositories as libraries, choose which paths import, watch import and embedding jobs, configure
  AI providers and budgets, and manage users, groups and tokens.
- **Readers**: developers on the same team who browse and search the imported docs at the exact
  version they use, often next to an editor and a terminal, for long stretches *(inferred: the
  #426 context says "people who read documentation for hours")*.
- **AI coding agents** are the other client (over MCP); people set them up from the Account page
  (API tokens, a ready-to-paste config).

## Product Purpose

Self-hosted, version-accurate documentation for AI coding agents and the people who work with them.
Point it at a git repository, pick the Markdown docs, and agents and people read them verbatim,
pinned to the tag, branch or commit imported. Success: people trust what they read is exactly what
the repository says at that version, and finding it is fast.

## Positioning

The version is a hard filter and the text is verbatim. Every answer names its library, version,
commit SHA and path, and links to the file on the git host. Ask about `v1.3` and you get `v1.3` or
"no result", never a plausible answer from `v1.4`. It is a self-hosted alternative to context7 with
the same MCP tools.

## Operating Context

- A web UI served by the same process as the REST API and MCP (`uvx exactdocs serve`, or Docker).
- The main loop: add a library, then choose docs, import, browse and search, and keep in sync.
- Instances hold dozens of libraries, hundreds of versions and jobs, and thousands of articles
  (#434: a trial instance has 26 libraries; one library has 7,000 articles).
- It is used on desktop next to an editor, and sometimes on a phone or tablet *(inferred: the UI
  already lays out for 390 px)*.

## Capabilities and Constraints

- Pages: sign-in and first-admin setup; libraries list; add library (preview of files, import
  progress); library page (version picker, file tree, tag filter, search, article reader with
  rendered and source views); global search; library settings (details, files and tags, versions,
  retrieval and AI, re-sync, removal); AI (providers, embedding, usage and budgets); users; account
  and API tokens.
- Stack: React 19, TanStack Router and Query, shadcn/ui on Tailwind v4, Vite. The built UI loads
  nothing from another origin (`scripts/check-dist.mjs`): fonts are self-hosted.
- The repository will be public: free shadcn/ui and free shadcnblocks.com blocks only, never premium
  code (confirmed 2026-11-23: no Pro licence; shadcn/ui is the component base, free blocks plus own
  compositions).
- Interface preferences (confirmed 2026-11-23): theme, contrast, text size, text spacing, reduced
  motion, a readable (dyslexia-friendly) font, always-underlined links, larger targets and the default
  UI font. Theme and text size switch directly from buttons in the top band; the rest from a dropdown
  in the band, whose last item opens the full "Interface" tab on the account page. Preferences are
  kept in the browser until the person signs in, then sync with the preferences stored for their
  account in the database.
- Terminology: library, version (a git ref resolved to a SHA), default version, article, chunk,
  tag, job, retrieval mode (BM25, hybrid, rerank, judge).

## Brand Commitments

- The name ExactDocs. The existing promise line "Documentation, word for word."
- No other committed brand assets (no logo file, no fixed colours or fonts) *(inferred from the
  repository)*.

## Evidence on Hand

- The fixture docs repository (`packages/exactdocs/tests/fixtures/docs-repo/`, "Acme Payments", a
  fictional SDK) is the only sample content. There are no customers, quotes or metrics, and none
  may be invented.

## Product Principles

1. Exact over plausible: always show which version, commit and path the text came from.
2. Reading comes first: long-form docs must be comfortable for hours, in light and dark.
3. Tell people what is happening: imports, embedding, saves and searches show progress and results.
4. Operators run it themselves: state, errors and limits say what to do next.

## Accessibility & Inclusion

WCAG 2.2 Level AA is required (confirmed 2026-11-23): keyboard navigation, visible focus (2.4.11),
target size (2.5.8), text spacing (1.4.12), reflow and resize to 200 %, AA contrast (axe clean) in
both themes, and `prefers-reduced-motion` respected (#426, #427). People can go further per account:
higher contrast, larger text, wider spacing, reduced motion independent of the OS, a
dyslexia-friendly font, underlined links and larger targets.
