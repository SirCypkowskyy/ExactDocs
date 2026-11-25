# Deviations from the plan

!!! abstract "TL;DR"
    - What MVP-1 turned out differently from the issues as first written. The source is the merged
      PRs.
    - The biggest changes: the chunker is `markdown-it-py` instead of Chonkie, the image budget grew
      from 300 MB to 400 MB, and the MCP tools take `ref` instead of `version`.
    - The REST client commands of the CLI moved to MVP-2; MVP-1 covers every action in the UI and
      the REST API.

| Plan | As built | Why |
|---|---|---|
| Chunker: Chonkie's Markdown recipe | `markdown-it-py` behind the `Chunker` port (#27) | Chonkie's recipe downloads rules from the Hugging Face Hub (network)<br/>Its `MarkdownChef` mis-detects fences in block quotes |
| Image budget 300 MB | 375 MB, measured 339 MB (#55)<br/>400 MB since DBOS (#65), measured 374.5 MB | The floor is the Python base image, git and ssh, and 57 MB of `.pyc` that keeps read-only containers from recompiling[^budgets] |
| MCP tools take `version` | `list_articles`, `read_article` and `search_docs` take `ref` (#38) | Matches `search_docs` and the REST `?ref=`<br/>The context7 tools keep their own names |
| `LibrarySummary.versions` (ref strings) | `refs` (kind, commit SHA, default flag; at most 50)<br/>plus `version_count` (#38) | Agents need the kind and commit SHA per version |
| No tags endpoint | `GET /libraries/{owner}/{repo}/tags` lists a version's tags with counts (#50) | The UI's tag filter needs them |
| A missing article is a plain 404 | The 404 lists up to five `close_matches` of the same version (#39) | Lets an agent correct a path in one step |
| Job list per library | Also `GET /jobs/latest` (newest job per version, #48)<br/>and `GET /libraries/{owner}/{repo}/access` (is the repository private, #51) | The library list and the article page would otherwise need a request per library |
| Re-sync reuses the import job | Re-syncs and re-imports of an existing version are `refresh` jobs<br/>Removal frees content with a `collect` job (#44, #45) | A late sync must never resurrect a removed version |
| Private repositories: a token field | Token or SSH deploy key, encrypted with `EXACTDOCS_SECRET_KEY` (#35):<br/>offered only to the library's own host<br/>sent only with a signed-in session | Threat model in the PR (#163) |
| stdio MCP reuses the app container | A separate `ReadOnlyContainer` (catalog and retrieval only)<br/>over a database opened `mode=ro` (#43) | Safe next to a running server<br/>Works before any account exists<br/>Creates no files |
| `exactdocs login` / `add` in MVP-1 | The CLI has `serve`, `admin create` and `admin reset-password`<br/>The REST client commands are MVP-2 | The UI and the REST API cover every action (CLI-01) |
| Setup page, tokens and library management in the UI | Built (#46 to #53) | As planned |

[^budgets]: See [Size and model-free budgets](../releasing.md#size-and-model-free-budgets).
