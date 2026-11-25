# Coverage matrix

!!! abstract "TL;DR"
    - Maps every story ID from the [user stories](../user-stories.md) to the issues that deliver it.
    - MVP-1 issues and MVP-2 / Next issues sit in separate columns.
    - The notes at the end list what was deferred, what the review rounds settled, which IDs were
      merged or split, and the dependencies that cross milestones.

Every story ID → the issues that deliver it. *(MVP-2)* parts are listed separately.

| Story | MVP-1 issues | MVP-2 / Next issues |
|---|---|---|
| AUTH-01 | E2-01, E2-02, E8-01 | - |
| AUTH-02 | E2-03, E7-07 (stdio), E8-02 | E6-02 (login), E6-03 (CLI) |
| CLI-01 | - | E6-02, E6-03, E10-04 (`reindex`), E10-06 (`backup`/`restore`) |
| LIB-01 | E3-01, E8-04 | - |
| LIB-02 | E3-02, E8-04 | E3-10 (images) |
| LIB-03 | - | E3-08, E8-11 |
| LIB-04 | E1-02, E1-03, E3-02, E3-05a, E8-04, E9-01 | - |
| LIB-05 | E3-04, E8-04 | - |
| LIB-06 | - | E3-09, E8-11 |
| LIB-07 | E3-06, E8-04, E8-10b, E7-05 | E3-09 (precedence) |
| LIB-08 | - | E6-03 |
| LIB-09 | - | E9-04, E8-10a, E4-05 (re-chunk only) |
| LIB-10 | - | E9-07 |
| LIB-11 | E3-07, E8-10b | E6-03 (CLI) |
| IMP-01 | E3-03 | E3-10 (images) |
| IMP-02 | E4-02, E1-04 | - |
| IMP-03 | - | E4-05 |
| IMP-04 | E4-01, E8-07, E7-03 | - |
| IMP-05 | E1-03, E1-05, E3-05a | E3-11 (DBOS resume) |
| IMP-06 | E1-05, E3-05b, E8-04 | - |
| TAG-01 | E4-03, E8-06 | E4-06, E8-14 (manual tags), E3-12 |
| TAG-02 | E4-03, E8-04 (rules set when adding) | E9-04, E8-10a (editing rules), E4-06 (manual tags combine) |
| TAG-03 | E4-03 (listing), E5-03 (search), E7-02, E7-04, E8-06, E8-09 | - |
| BRW-01 | E8-06, E8-07 | E8-12 (imported images) |
| BRW-02 | - | E8-12 |
| BRW-03 | E8-06, E5-03 (links) | - |
| BRW-04 | E8-06 | E8-13, E3-12 (renames) |
| BRW-05 | E8-03 | - |
| SRCH-01 | E5-01, E5-02, E5-03, E5-04, E8-09 | E12-02 (PostgreSQL parity) |
| SRCH-02 | E5-02, E5-03, E8-09 | - |
| SRCH-03 | - | E5-06, E8-15 |
| MCP-01 | E7-02 | - |
| MCP-02 | E7-02 | - |
| MCP-03 | E7-03 | E7-08 (resources) |
| MCP-04 | E1-04, E5-03, E7-03, E7-04, E9-01 (`stale_chunk` scenario) | E7-09 (new location), E3-12 (renames) |
| MCP-05 | E5-03, E7-04 | E11-01 (modes) |
| MCP-06 | - | E7-10 |
| MCP-07 | E4-01 (import), E7-02, E7-05 (context7 tools) | - |
| MCP-08 | - | E12-12 (Next: Teams & integrations, needs ACL-01) |
| C7-01 | E7-05 | - |
| C7-02 | E7-06 | E3-09 (`rules`), E11-01 (library mode) |
| C7-03 | - | E6-04 |
| C7-04 | - | E6-05 |
| SYNC-01 | E9-01, E8-10b | E6-03 (CLI) |
| SYNC-02 | - | E9-05 |
| SYNC-03 | E9-03, E8-10b | - |
| SYNC-04 | E9-01 (last good version, error on the job), E8-03 (error shown) | E9-02 (error codes, moved tags), E9-06 (moved-tag re-import) |
| RUN-01 | E1-01, E10-03a, E10-03b | - |
| RUN-02 | E10-02, E4-02 | E11-01 (lazy `[ai]` extra) |
| RUN-03 | E10-01, E7-02 | E10-07 (collector only) |
| RUN-04 | - | E10-04 |
| RUN-05 | E1-06, E5-04 | E11-02 |
| RET-01 | - | E11-03, E11-04, E11-15, E11-16, E11-17 (pgvector), E11-18, E11-19 |
| RET-02 | - | E11-05, E11-07, E11-19 (local) |
| RET-03 | - | E11-06 (incl. extra headers), E11-15 (providers), E11-20 (image) |
| RET-04 | - | E11-09, E11-10, E11-11 (and E10-07 for spans) |
| RET-05 | - | E11-12 |
| RET-06 | - | E11-01, E11-14 |
| RET-07 | - | E11-08, E11-14 (and E10-08 for metrics) |
| RET-08 | - | E11-13 |
| RET-09 | - | E11-02, E11-11 (agentic trace check) |
| ACL-01 | - | E12-03, E12-04 |
| ACL-02 | - | E12-05, E12-06 |
| ACL-03 | - | E12-07 |
| ACL-04 | - | E12-08 |
| ACL-05 | - | E12-09 |
| ACL-06 | - | E12-13 |
| TEAM-01 | - | E12-01, E12-02, E11-17, E11-18 (Supabase) |
| TEAM-02 | - | E12-10 |
| TEAM-03 | - | E12-11 |
| OPS-01 | - | E10-07, E10-08 |
| OPS-02 | - | E10-05, E10-06 |

!!! warning "Deferred and cross-milestone notes"
    - **Intentionally deferred:** all *Later* ideas (no issues). MCP-08 is placed in
      *Next: Teams & integrations* because it depends on ACL-01.
    - **Settled in review round 1:** library-ID case and charset (E1-02), SSH host-key policy
      (E3-04), SQLite vector storage (E11-03, Decisions *Vector storage*), the persistence stack
      (E1-01, Decisions *Persistence*), and extra local users (ACL-06, E12-13).
    - **Settled in review round 2:** private repositories (E3-04, LIB-05) stay in MVP-1; E6-02,
      E6-03, E9-02, E9-04 and E8-10a moved to MVP-2, so MVP-1 manages tokens and libraries in the
      web UI (title edits and adding versions moved from E8-10a to E8-10b); the smoke test
      imports the mounted fixture via `file://` and needs neither GitHub nor this repository.
    - **Merged or split IDs:** E7-01 → E7-02, E5-05 → E7-03, E8-05 → E8-04, E8-08 → E8-06;
      E4-04 dissolved into E4-03 (listing) and E5-03 (search); E3-05 → E3-05a, E3-05b;
      E8-10 → E8-10a, E8-10b; E10-03 → E10-03a, E10-03b.
    - **Cross-milestone dependencies:** RET-07 metrics need E10-08; RUN-03's test grows with
      E10-07 (collector) and E11 (model endpoints); E12-01 and E12-02 moved to *Next: AI
      retrieval* (2026-11) and pgvector is E11-17; E12-10
      needs MVP-2's E9-05, E4-05 and E6-02.
