# MVP-1 build order

!!! abstract "TL;DR"
    - The order across epics is built around the critical path, the longest dependency chain:
      11 issues from E1-01 to E10-03a, **28.5 days** long.
    - Side chains with zero or little slack are listed below, as is the web track, which builds
      against mocked OpenAPI types.
    - MVP-1 totals 45 issues (8 S, 30 M, 7 L): 59 to 133 person-days, 114.5 at the point estimate.
    - The track table shows what runs beside the path and what each track demonstrates.

The order is built around the **critical path**, the longest dependency chain; a slip on it
moves the MVP-1 date:

**E1-01 → E1-02 → E1-03 → E1-04 → E4-02 → E3-05a → E3-06 → E7-05 → E7-06 → E7-07 → E10-03a**

Counted by size (S=1, M=2.5, L=4.5 days) over the *Depends on* lines, the path is **28.5 days**
long. Prerequisites that must be merged before their step on the path: E4-01 and E1-06 before
E4-02; E1-05, E3-03 and E4-03 before E3-05a; E7-02 and E5-03 before E7-05; E7-03 and E7-04
before E7-07; E2-03 and E10-02 before E10-03a. Side chains:

- **Just as critical (zero slack):** E1-02 → E3-01 → E3-02 → E3-03 → E3-05a and
  E3-02 → E4-03 → E3-05a both reach E3-05a on day 12.5, like E4-02.
- **Near-critical:** E1-04 → E5-02 → E5-03 → E7-05 and E4-03 → E7-02 → E7-05 (1 day of slack);
  E7-02 → E7-03 → E7-07 (1.5 days; E7-03 is L since it absorbed E5-05).
- **Web:** web issues are built against the mocked OpenAPI types, so their backend dependencies
  gate merging, not starting. Even counted as hard dependencies, the longest web chain
  E3-07 → E3-04 → E8-04 → E10-03b ends on day 27.5 (1 day of slack); E9-01 → E8-10b ends on
  day 26.5.

MVP-1 totals 45 issues (8 S, 30 M, 7 L): **59-133 person-days** at the low and high ends of
the sizes (S=1, M=1-3, L=3-5), 114.5 at the S=1, M=2.5, L=4.5 point estimate. Everything else
runs beside the path:

| Track | Issues (in order) | Starts | Demonstrable result |
|---|---|---|---|
| Critical path | E1-01, E1-02, E1-03, E1-04, E4-02, E3-05a, E3-06, E7-05, E7-06, E7-07, E10-03a | day 1 | Migrated SQLite in the data dir →<br/>IDs and default version →<br/>manifests →<br/>chunk sets →<br/>chunker →<br/>atomic import →<br/>README defaults →<br/>`resolve-library-id` →<br/>`query-docs` →<br/>stdio →<br/>five-minute smoke demo |
| Day 1, in parallel | E1-06, E5-01, E6-01, E4-01 | day 1 | Fixture repo builds in tests;<br/>identifier tokenizer;<br/>`/api/v1` conventions and OpenAPI;<br/>safe parser |
| Jobs | E1-05 | after E1-01 | Jobs persist and restart cleanly |
| Identity | E2-01, E2-02, E2-03 | E2-01 after E1-01 + E6-01 | Nothing reachable before setup; sessions and tokens guard REST and MCP |
| Git importer | E3-01, E3-02, E3-03, E4-03; E3-04 after E3-07 | E3-01 after E1-02 | Libraries created from any git URL, public or private;<br/>a sparse, shallow fetch lands in a temp dir;<br/>tags and tag filters on listings |
| Import follow-ups | E3-05b, E3-07 | after E3-05a | Skipped files with reasons; a second version |
| Search & MCP | E5-02, E5-03, E5-04; E7-02, E7-03, E7-04 | E5-02 after E1-04 + E5-01; E7-02 after E1-03 + E4-03 | FTS5 and version-pinned search; ranking suite green; MCP browse, read and search tools |
| Sync & lifecycle | E9-01, E9-03 | E9-01 after E3-05a + E7-03 | Re-sync (incl. stale chunk IDs and a failed sync keeping the last good version), removal + GC |
| Web | E8-01, E8-02, E8-03, E8-04, E8-06, E8-07, E8-09, E8-10b | E8-01 after E2-02, built against the mocked OpenAPI types;<br/>each UI issue merges once its endpoints exist | The whole loop in the browser, incl. tokens and private repositories |
| Run it | E10-02, E10-01, E10-03b | E10-02 after E4-02;<br/>E10-01 after E7-06;<br/>E10-03b after the web issues (E10-03a ends the critical path) | Size budgets, privacy test, `docker run` smoke, `uvx` smoke and the browser end-to-end test (MVP-1 exit) |
