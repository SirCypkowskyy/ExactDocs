# context7 contract

Vendored description of the context7 MCP tools ExactDocs mirrors, so that switching a client
from context7 to ExactDocs is a URL change.

- Pinned to **`@upstash/context7-mcp` 4.5.0** (`packages/mcp/src/index.ts` in
  <https://github.com/upstash/context7>).
- `resolve-library-id.json`: tool name and input schema (`query` and `libraryName`, both required
  strings). Descriptions are left out on purpose; only names, types and required-ness are the
  contract.
- `query-docs.json`: `libraryId` and `query` required strings, `language` optional string.
  context7 returns the text of its `/v2/context` API as one text block, `isError` on failure;
  ExactDocs puts the notice first and mirrors the `### title` / `Source:` / text blocks.
- `session.json`: a **hand-built** session (not a captured transcript) using both tools with realistic arguments; `tests/bootstrap/test_context7_session_replay.py`
  replays it and requires no errors.
- `tests/bootstrap/test_context7_contract.py` checks that ExactDocs' tool has this name and that
  its input schema matches: every property here exists with the same type and the set of required
  arguments is the same (a client sending only context7's arguments is accepted, and ExactDocs
  requires nothing more).

## Updating deliberately

1. Read context7's changelog and the `registerTool` calls in the new release.
2. Edit the JSON files to match the new schema and change the pinned version above.
3. Run `uv run pytest packages/exactdocs/tests/bootstrap/test_context7_contract.py`. A failure
   means ExactDocs must change before the pin moves; do not loosen the test to get green.
4. Mention the version bump in the PR.

Deliberately **not mirrored**: `QUERY_DOCS_ALIASES` (`libraryID`, `libraryName`, ... for `libraryId`) and context7's argument aliases (`GLOBAL_ALIASES` in `index.ts`, e.g.
`userQuery` and `question` for `query`). They are a workaround for sloppy model output, not part of
the schema; accepting them would make `query` optional and break the equal-required-set check
below. ExactDocs refuses unknown arguments (tested). Length caps: `libraryName` 256 and `query`
1000 characters; context7 has none, but a longer value is far beyond a realistic call.

Output text format (`Available Libraries:` and the `- Title:` / `- Context7-compatible library
ID:` / `- Description:` / `- Versions:` / `- Source:` lines, entries separated by `----------`)
is mirrored by `exactdocs.retrieval.adapters.driving.mcp.format_library` and pinned by a
golden-text test in `tests/retrieval/test_resolve_library_id.py`.

## The `query-docs` payload

Blocks are `### <heading path>`, `Source: <link>`, `Chunk: <id>` and the verbatim text, separated
by 32 dashes. A chunk too large for the budget is a block with no text, saying to fetch it with
`read_chunk`. A last line states how many matching chunks did not fit. The budget
(`EXACTDOCS_QUERY_DOCS_TOKEN_BUDGET`, at least 500) covers the whole payload, notice included, and
counts a token as 4 characters; that undercounts CJK text and dense code. `language` reorders the
best 50 matches; it does not filter.
