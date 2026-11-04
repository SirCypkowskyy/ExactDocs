# context7 contract

Vendored description of the context7 MCP tools ExactDocs mirrors, so that switching a client
from context7 to ExactDocs is a URL change.

- Pinned to **`@upstash/context7-mcp` 4.5.0** (`packages/mcp/src/index.ts` in
  <https://github.com/upstash/context7>).
- `resolve-library-id.json`: tool name and input schema (`query` and `libraryName`, both required
  strings). Descriptions are left out on purpose; only names, types and required-ness are the
  contract.
- `tests/bootstrap/test_context7_contract.py` checks that ExactDocs' tool has this name and that
  its input schema is a **superset**: every property here exists with the same type and every
  required argument here is required there, and ExactDocs requires nothing more.

## Updating deliberately

1. Read context7's changelog and the `registerTool` calls in the new release.
2. Edit the JSON files to match the new schema and change the pinned version above.
3. Run `uv run pytest packages/exactdocs/tests/bootstrap/test_context7_contract.py`. A failure
   means ExactDocs must change before the pin moves; do not loosen the test to get green.
4. Mention the version bump in the PR.

Output text format (`Available Libraries:` and the `- Title:` / `- Context7-compatible library
ID:` / `- Description:` / `- Versions:` / `- Source:` lines, entries separated by `----------`)
is mirrored by `exactdocs.retrieval.adapters.driving.mcp.format_library`.
