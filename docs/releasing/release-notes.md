# Release notes template

!!! abstract "TL;DR"
    - The release workflow creates the GitHub Release with generated notes, grouped by
      `.github/release.yml`.
    - PRs labelled `requires reindex` get their own section.
    - Edit the release afterwards so it follows the template below. Leave out any section that
      would be empty, except *Upgrading*.

```markdown
## Highlights
- <what a user can do now that they could not before>

## Upgrading
Start the new version on the same data directory: the database is migrated on start.

### Requires reindex
<!-- Only when FORMAT changed (a PR labelled `requires reindex`); otherwise write "No reindex needed." -->
Search keeps answering as before until you run, where the server runs:
`exactdocs reindex` (Docker: `docker exec exactdocs exactdocs reindex`). It rebuilds the index
while the server keeps serving; until then `/api/health` reports `"reindex_required": true`.
Why: <what search finds better after it>.

### Breaking changes
- <configuration, REST, MCP tool contract or data-format changes; MAJOR only after 1.0>

## Fixes
- ...
```

When a reindex is needed and why: [Upgrades, migrations and "requires reindex"](upgrades.md).
