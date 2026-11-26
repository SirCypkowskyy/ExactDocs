# Filing

!!! abstract "TL;DR"
    - How the plan was filed on GitHub: milestones, the `type: epic` label, epics, features in
      build order, sub-issues, "blocked by" links, then promotion to `status: ready`.
    - Every issue was filed as `status: triage`. Record each new number in `filed.tsv` and pause
      about 1 s between write calls.
    - Sizes: S ≤ 1 day, M 1-3 days, L 3-5 days; anything bigger is split.
    - The architecture ground rules at the end apply to every issue.

Each issue in the epic pages is ready to paste into the **Feature** form (`.github/ISSUE_TEMPLATE/feature.yml`):

| Plan field | Issue form |
|---|---|
| Title (`feat: ...`) | Title, unchanged; drop the plan ID, add it as the first line of *Notes* (`Plan: E3-06`) |
| Context | *Context* (business context); add the story IDs, e.g. `Stories: LIB-01, LIB-04` |
| Expected behavior | *Expected behavior*: backend Gherkin becomes the behave scenario as written; E8 (web) Gherkin becomes vitest tests; foundation issues list testable statements verified by pytest (see the ground rules) |
| Criteria of success | *Criteria of success*: checkbox list as-is |
| Area | *Area* dropdown values |
| Notes, Depends on | *Notes*: hints (citing the [Decisions](../decisions/index.md)), out-of-scope, `Depends on #<n>` once the dependencies have issue numbers |

Labels: one type (`type: feature`, or `type: chore` for E1-06 and E6-01), one status, and one or
more of `area: backend`, `area: web`, `area: infra`. The status in each issue's *Labels* line is
the status it gets **after promotion**. **Every issue is filed as `status: triage`**; after review
round 3, all MVP-1 issues and the 12 epics are promoted to `status: ready` in bulk; MVP-2 and Next
issues are promoted when their milestone starts.

**Record every created number** in `filed.tsv` (plan ID, issue number), since later steps look
dependencies and epics up there, and **pause about 1 s between write calls** (GitHub's secondary
rate limits):

```bash
url=$(gh issue create --title "feat: <outcome>" … --body-file body.md)
echo "E3-06 ${url##*/}" >> filed.tsv
sleep 1
```

Filing steps, in this order:

1. **Milestones.** Create the five milestones (goal from the [Milestones](index.md#milestones) table as
   description):

    ```bash
    gh api repos/{owner}/{repo}/milestones -f title="MVP-1" \
      -f description="The main loop works end to end for one admin user with zero external services."
    # repeat for "MVP-2", "Next: AI retrieval", "Next: Teams & integrations", "Next: Operations"
    ```

2. **Label.** `type: epic` is in `.github/labels.yml`; apply it with
   `.agents/skills/working-on-issues/scripts/sync-labels.sh`.
3. **Epics.** File the 12 epic tracking issues, titled `epic: E<n> <name>` (e.g.
   `epic: E3 Git import`), each with the epic's goal and stories from the [Epics](index.md#epics) table,
   labels `type: epic` and `status: triage`, no milestone (an epic spans milestones). Record
   each epic's number in `filed.tsv` under its epic ID (`E3`), for step 5:

    ```bash
    url=$(gh issue create --title "epic: E3 Git import" --label "type: epic" --label "status: triage" --body-file epic.md)
    echo "E3 ${url##*/}" >> filed.tsv; sleep 1
    ```

    Once its features are filed (step 4), edit each epic's body to add a task list of them
    (`- [ ] #<n>`, one line per feature) as a fallback view of the sub-issues.
4. **Features, in topological build order** (not page order), so every dependency already has a
   number. `body.md` uses the form's headings: `### Context`, `### Expected behavior`,
   `### Criteria of success`, `### Area`, `### Notes`. For MVP-1:

    E1-01, E1-06, E5-01, E6-01, E4-01, E1-02, E1-05, E2-01, E1-03, E2-02, E1-04, E3-01, E2-03,
    E3-02, E4-02, E5-02, E3-03, E4-03, E3-05a, E3-05b, E3-06, E3-07, E3-04, E5-03, E5-04, E7-02,
    E7-03, E7-04, E7-05, E7-06, E7-07, E9-01, E9-03, E8-01, E8-02, E8-03, E8-04, E8-06, E8-07,
    E8-09, E8-10b, E10-01, E10-02, E10-03a, E10-03b.

    Then the other milestones in this order (dependencies on earlier milestones are already
    filed):

    - **MVP-2:** E6-02, E6-03, E9-02, E9-04, E3-08, E3-09, E3-10, E3-11, E3-12, E4-05, E4-06,
      E5-06, E6-05, E6-04, E7-08, E7-09, E7-10, E8-10a, E8-11, E8-12, E8-13, E8-14, E8-15, E9-05,
      E9-06, E9-07, E10-04.
    - **Next: Operations:** E10-05, E10-06, E10-07, E10-08.
    - **Next: AI retrieval:** E11-01, E11-02, E11-03, E11-04, E11-05, E11-06, E11-08, E11-07,
      E11-09, E11-10, E11-11, E11-12, E11-13, E11-14.
    - **Next: Teams & integrations:** E12-01, E12-02, E12-03, E12-04, E12-13, E12-05, E12-06,
      E12-07, E12-08, E12-09, E12-10, E12-11, E12-12.

    ```bash
    url=$(gh issue create --title "feat: <outcome>" --milestone "MVP-1" \
      --label "type: feature" --label "status: triage" --label "area: backend" \
      --body-file body.md)
    echo "E3-06 ${url##*/}" >> filed.tsv; sleep 1
    ```

5. **Sub-issues.** Link each feature as a GitHub sub-issue of its epic (the API takes the
   issue's database `id`, not its number):

    ```bash
    child_id=$(gh api repos/{owner}/{repo}/issues/<feature-number> --jq .id)
    gh api repos/{owner}/{repo}/issues/<epic-number>/sub_issues -F sub_issue_id="$child_id"
    ```

6. **Blocked by.** First check once that the dependencies API is available:
   `gh api repos/{owner}/{repo}/issues/<n>/dependencies/blocked_by`. If it returns 404, skip
   this step and rely on the `Depends on #<n>` lines and the epic task lists. Otherwise, for
   every *Depends on*, add a GitHub "blocked by" relationship in addition to the
   `Depends on #<n>` line in *Notes*. Add "blocked by" only for whole-issue dependencies: skip
   E11-08 → E10-08 (metrics only), E12-02 → E11-03 (pgvector part only) and E12-01 ('MVP-1').

    ```bash
    blocker_id=$(gh api repos/{owner}/{repo}/issues/<dependency-number> --jq .id)
    gh api repos/{owner}/{repo}/issues/<feature-number>/dependencies/blocked_by -F issue_id="$blocker_id"
    ```

7. **Promotion.** After review round 3, promote every MVP-1 issue and every epic to
   `status: ready` in bulk:

    ```bash
    { gh issue list --milestone "MVP-1" --label "status: triage" --limit 200 --json number --jq '.[].number'
      gh issue list --label "type: epic" --label "status: triage" --limit 50 --json number --jq '.[].number'; } |
      xargs -I{} sh -c 'gh issue edit {} --remove-label "status: triage" --add-label "status: ready"; sleep 1'
    ```

Sizes: **S** ≤ 1 day, **M** 1-3 days, **L** 3-5 days. Anything bigger is split.

MVP-1 issues are written in full. MVP-2 and Next issues use a compact form: the paragraph is the
*Context*, the Gherkin block the *Expected behavior*, and the checklist the *Criteria of success*;
they are completed (tests, docs) when promoted to `status: ready`. E6-02, E6-03, E9-02, E9-04
and E8-10a moved from MVP-1 to MVP-2 in review round 2 and keep their full form. Every issue
implicitly includes "`just check` passes" and "architecture tests green".

!!! note "Architecture ground rules used by every issue"
    Work goes through each domain's standard modules (`models`, `dtos`, `ports/driving`,
    `ports/driven`, `use_cases`, `module`, `adapters/...`; see [Architecture](../architecture/domains.md#inside-a-domain-the-fixed-module-set)).
    The plan adds two domains next to `catalog` and `retrieval`, matching the form's *Area* values:

    | Domain | Owns |
    |---|---|
    | `identity` | the admin account, sessions, API tokens |
    | `catalog` | libraries, versions, settings (paths, tag rules, chunking), manifests, article content, default version |
    | `ingestion` | git access, credentials, jobs and the worker, parsing, chunking, import/sync use cases; applies catalog settings |
    | `retrieval` | chunk sets, version-scoped chunk IDs, the search port and its adapters, `search_docs`, `read_chunk`, `resolve-library-id`, `query-docs` |

    Domains talk only through driven ports implemented by bridges in `bootstrap/bridges.py`.
    **Bridges are one-way: retrieval → catalog, ingestion → catalog / retrieval.** Catalog calls
    no other domain, and nothing calls ingestion. There are **no cross-domain foreign keys**:
    a domain holds another domain's IDs (e.g. manifest IDs) by value.

    Persistence (Decisions *Persistence*): SQLAlchemy Core (async, no ORM) with aiosqlite; one
    Alembic history owned by `bootstrap` (`render_as_batch=True`; FTS5 tables via `op.execute`);
    tables prefixed per domain (`catalog_`, `retrieval_`, ...); a domain never reads another
    domain's tables.

    Every use case gets its REST route under `/api/v1` in the same PR (REST is the only API of the
    UI and the CLI). Routes that need a ref and an article path take both as query parameters
    (`?ref=` and `?path=`; Decisions *Refs containing `/`*).

    **How issues are verified.** Foundation issues (E1-*, E4-02, E5-01, E5-02) are verified by
    pytest contract and integration tests; their *Expected behavior* lists testable statements,
    not behave scenarios. Every other backend acceptance scenario is a behave scenario that runs
    through REST or MCP, never through internals. Before E3-05a merges, *Given* steps seed
    fixture-shaped versions through the catalog and retrieval driving ports (`StoreManifest`,
    `IndexManifest`, `ActivateManifest`) with a shared step; *When* and *Then* go through REST
    or MCP. E8 (web) Gherkin maps to vitest tests against
    mocked API responses. One Playwright end-to-end test (setup → add fixture → browse → search)
    runs in CI with E10-03b.
